"""FFmpeg process management and app log for troubleshooting."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models import Channel, FFmpegProfile

_LOG_LEVEL_ORDER = {"debug": 0, "info": 1, "warn": 2, "error": 3}

_FRAME_STAT_RE = re.compile(r"^frame=\s*\d+")
_HLS_OPEN_RE = re.compile(r"^\[hls\s*@\s*0x[0-9a-f]+\]", re.IGNORECASE)
_CODEC_ADDR_RE = re.compile(r"^\[[a-z0-9_]+\s*@\s*0x[0-9a-f]+\]", re.IGNORECASE)
_FFMPEG_BOILERPLATE_RE = re.compile(
    r"^(?:ffmpeg version|built with|  configuration:|  lib(?:av|sw|post)|"
    r"Input #|Output #|Stream #|  Stream #|Stream mapping:|Press \[q\]|"
    r"  Duration:|  Metadata:|    (?:encoder|icy-|StreamTitle|icy_|bitrate|start:))",
    re.IGNORECASE,
)
_APP_LEVEL_RE = re.compile(r"^\[[^\]]+\] \[(DEBUG|INFO|WARN|ERROR)\] ", re.IGNORECASE)


def classify_channel_log_line(line: str) -> str:
    """Return 'debug', 'info', 'warn', or 'error' for a channel/FFmpeg log line."""
    s = line.rstrip()
    if not s:
        return "debug"
    lower = s.lower()

    if _FRAME_STAT_RE.match(s):
        return "debug"
    if _HLS_OPEN_RE.match(s):
        return "debug"
    if _FFMPEG_BOILERPLATE_RE.match(s):
        return "debug"
    if _CODEC_ADDR_RE.match(s):
        if "error" in lower or "failed" in lower or "invalid" in lower:
            return "error"
        if "warning" in lower:
            return "warn"
        if "qavg:" in lower or "lsize=" in lower:
            return "info"
        return "debug"

    if s.startswith("[metadata]"):
        if "art download failed" in lower or ("error" in lower and "cache" not in lower):
            return "warn"
        if "cache hit" in lower or "(from cache)" in lower or "art: using default" in lower:
            return "debug"
        if "art at startup:" in lower:
            return "info"
        return "info"

    if lower.startswith("exiting normally") or lower.startswith("video:") or lower.startswith("audio:"):
        return "info"

    if "error" in lower or "failed" in lower or "invalid" in lower or "no such file" in lower:
        return "error"
    if "warning" in lower:
        return "warn"

    return "debug"


def classify_app_log_line(line: str) -> str:
    """Return 'debug', 'info', 'warn', or 'error' for an application log line.

    Lines written by append_app_log() contain a [LEVEL] tag after the timestamp and are
    parsed directly. Legacy lines (no tag) fall back to content-based heuristics.
    """
    s = line.strip()
    if not s:
        return "debug"
    m = _APP_LEVEL_RE.match(s)
    if m:
        return m.group(1).lower()
    lower = s.lower()
    if "ffmpeg exited unexpectedly" in lower or "auto-restarting" in lower or "may be due to gpu" in lower or "idle for >" in lower:
        return "warn"
    if "auto-restart failed" in lower or "start failed" in lower or "watch task error" in lower:
        return "error"
    if "stream ensure" in lower:
        return "debug"
    return "info"


def filter_log_lines(lines: list[str], level: str, is_app_log: bool = False) -> list[str]:
    """Return only lines at or above the given log level."""
    min_level = _LOG_LEVEL_ORDER.get((level or "debug").lower(), 0)
    if min_level == 0:
        return lines
    classify = classify_app_log_line if is_app_log else classify_channel_log_line
    return [ln for ln in lines if _LOG_LEVEL_ORDER.get(classify(ln), 0) >= min_level]

APP_LOG_FILENAME = "app.log"
MAX_CHANNEL_LOG_BYTES = 2 * 1024 * 1024
TRIM_KEEP_BYTES = 1 * 1024 * 1024


def _log_path(channel_id: str) -> Path:
    assert settings.logs_dir
    return settings.logs_dir / f"ffmpeg_{channel_id}.log"


def get_app_log_path() -> Path:
    """Path to the application log (non-FFmpeg events for troubleshooting)."""
    assert settings.logs_dir
    return settings.logs_dir / APP_LOG_FILENAME


def append_app_log(message: str, level: str = "info") -> None:
    """Append a timestamped, level-tagged line to the application log."""
    if not settings.logs_dir:
        return
    path = get_app_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tag = (level or "info").upper()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{tag}] {message.strip()}\n")
    except OSError:
        pass


def build_ffmpeg_args(
    channel: Channel,
    profile: FFmpegProfile,
    input_url: str,
    output_path_or_url: str,
    overlay_filter: str | None = None,
) -> list[str]:
    """Build ffmpeg command args (no -i input yet if overlay is used)."""
    args = [
        "-y",
        "-re",
        "-i", input_url,
    ]
    if overlay_filter:
        args.extend(["-vf", overlay_filter, "-i", input_url])
    args.extend([
        "-c:v", profile.video_codec,
        "-b:v", profile.video_bitrate,
        "-preset", profile.preset,
        "-pix_fmt", profile.pixel_format,
        "-c:a", profile.audio_codec,
        "-b:a", profile.audio_bitrate,
    ])
    args.extend(profile.extra_args)
    args.append(output_path_or_url)
    return args


async def start_channel_ffmpeg(
    channel_id: str,
    full_cmd: list[str],
    on_log: Callable[[str], None] | None = None,
    ffmpeg_executable: str = "ffmpeg",
) -> asyncio.subprocess.Process | None:
    """Start FFmpeg process and optionally stream stderr to on_log and log file."""
    log_path = _log_path(channel_id)
    executable = (ffmpeg_executable or "ffmpeg").strip() or "ffmpeg"
    try:
        proc = await asyncio.create_subprocess_exec(
            executable,
            *full_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _pipe_stderr(stream: asyncio.StreamReader) -> None:
            with open(log_path, "ab") as f:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace")
                    if on_log:
                        on_log(decoded)
                    f.write(line)
                    f.flush()

        asyncio.create_task(_pipe_stderr(proc.stderr))
        return proc
    except Exception:
        return None


def get_channel_log_path(channel_id: str) -> Path:
    return _log_path(channel_id)


def _trim_channel_log_if_needed(path: Path) -> None:
    """If log file exceeds MAX_CHANNEL_LOG_BYTES, keep only the last TRIM_KEEP_BYTES."""
    if not path.exists():
        return
    try:
        if path.stat().st_size <= MAX_CHANNEL_LOG_BYTES:
            return
        content = path.read_bytes()
        if len(content) <= TRIM_KEEP_BYTES:
            return
        tail = content[-TRIM_KEEP_BYTES:]
        newline_at = tail.find(b"\n")
        if newline_at != -1:
            tail = tail[newline_at + 1:]
        path.write_bytes(tail)
    except OSError:
        pass


def append_metadata_log(channel_id: str, message: str) -> None:
    """Append a line to the channel log (for metadata scraping troubleshooting)."""
    if not settings.logs_dir:
        return
    path = _log_path(channel_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _trim_channel_log_if_needed(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[metadata] {message.strip()}\n")
    except OSError:
        pass
