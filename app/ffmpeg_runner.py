"""FFmpeg process management and app log for troubleshooting."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models import Channel, FFmpegProfile

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


def append_app_log(message: str) -> None:
    """Append a timestamped line to the application log (channel start/stop, errors, etc.)."""
    if not settings.logs_dir:
        return
    path = get_app_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.open("a", encoding="utf-8").write(f"[{ts}] {message.strip()}\n")
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
        path.open("a", encoding="utf-8").write(f"[metadata] {message.strip()}\n")
    except OSError:
        pass
