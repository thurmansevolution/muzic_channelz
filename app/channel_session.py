"""ChannelSession: ErsatzTV-style per-channel session worker.

Each channel gets one ChannelSession that owns its entire ffmpeg lifecycle.
The session stays alive across crashes, tracks cumulative PTS offset, and
restarts ffmpeg with -output_ts_offset so Plex/Kodi never see timestamps
jump backwards.  During the restart gap the existing m3u8 and recent .ts
files are preserved so in-flight conversion ffmpegs (hdhr.py) keep reading.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable

from app.config import settings
from app.ffmpeg_runner import start_channel_ffmpeg, append_app_log, append_metadata_log
from app.models import AdminState, Channel, FFmpegProfile, FFmpegSettings
from app.overlay import (
    default_overlay_placements,
    ensure_stock_background_png,
    ensure_stock_dark_background_png,
    get_placement,
)
from app.now_playing import now_playing_loop, write_now_playing_files
from app.store import load_admin_state

_log = logging.getLogger("app.channel_session")


def _get_profile(state: AdminState, profile_id: str | None) -> FFmpegProfile | None:
    if profile_id:
        p = next((p for p in state.ffmpeg_profiles if p.id == profile_id), None)
        if p:
            return p
    return state.ffmpeg_profiles[0] if state.ffmpeg_profiles else None


def _get_station_name(channel: Channel, state: AdminState) -> str:
    want = (channel.azuracast_station_id or "").strip()
    if not want:
        return ""
    for st in state.azuracast_stations:
        if (st.name or "").strip() == want or (st.station_shortcode or "").strip() == want:
            return (st.name or "").strip() or (st.station_shortcode or "").strip()
    return ""


def _get_azuracast_listen_url(channel: Channel, state: AdminState) -> str | None:
    want = (channel.azuracast_station_id or "").strip()
    if not want:
        return None
    for st in state.azuracast_stations:
        name = (st.name or "").strip()
        shortcode = (st.station_shortcode or "").strip()
        if not st.base_url or not shortcode:
            continue
        if name == want or shortcode == want:
            return f"{st.base_url.rstrip('/')}/listen/{shortcode}/radio.mp3"
    return None


class ChannelSession:
    """
    Persistent session worker for one channel.

    Mirrors ErsatzTV's IHlsSessionWorker:
      - One long-lived asyncio Task per channel (self._task)
      - Manages the ffmpeg process; on crash, auto-restarts with correct PTS
      - Tracks cumulative pts_offset so output timestamps are always monotonic
      - On restart: preserves recent .ts files + index.m3u8 so conversion
        ffmpegs serving Plex/Kodi keep reading during the 3-15s gap
      - On user stop: cleans up all HLS files
    """

    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.pts_offset: float = 0.0
        self.session_start: float = time.time()

        self._proc: asyncio.subprocess.Process | None = None
        self._used_hw_accel: bool = False
        self._stop_requested: bool = False
        self._task: asyncio.Task | None = None
        self._last_restart_mono: float = 0.0
        self._last_activity: float = time.time()

        self._np_stop: asyncio.Event | None = None
        self._np_task: asyncio.Task | None = None

        self.log_listeners: list[Callable[[str], None]] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def last_activity(self) -> float:
        return self._last_activity

    def notify_activity(self) -> None:
        self._last_activity = time.time()

    def start(self) -> None:
        """Create and schedule the session worker task."""
        self._stop_requested = False
        self._last_activity = time.time()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the session, kill ffmpeg, and remove all HLS files."""
        self._stop_requested = True
        await self._kill_proc()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._stop_np()
        self._cleanup_hls_files()
        append_app_log(f"channel {self.channel_id} stopped", "info")

    # ------------------------------------------------------------------ #
    # Session worker loop — ErsatzTV HlsSessionWorker equivalent          #
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        first_run = True
        consecutive_failures = 0
        _MAX_CONSECUTIVE_FAILURES = 10
        while not self._stop_requested:
            state = await load_admin_state()
            ch = next((c for c in (state.channels or []) if c.id == self.channel_id), None)
            if not ch or not ch.enabled:
                break

            if not first_run:
                await self._cleanup_stale_segments(state)

            proc, used_hw = await self._launch_ffmpeg(
                state, ch,
                clean_start=first_run,
                pts_offset_secs=self.pts_offset,
            )

            if proc is None:
                append_app_log(f"channel {self.channel_id}: failed to launch ffmpeg — session ending", "error")
                break

            self._proc = proc
            self._used_hw_accel = used_hw
            run_start = time.monotonic()
            first_run = False

            append_app_log(f"channel {self.channel_id} started", "info")

            returncode = await proc.wait()
            self._proc = None

            if self._stop_requested:
                break

            run_duration = time.monotonic() - run_start
            self.pts_offset += run_duration

            append_app_log(
                f"channel {self.channel_id}: ffmpeg exited (code={returncode}) after "
                f"{run_duration:.1f}s — pts_offset now {self.pts_offset:.1f}s",
                "debug",
            )

            if returncode != 0 and used_hw:
                append_app_log(
                    f"channel {self.channel_id}: hardware encoder exited abnormally — "
                    f"may be GPU/driver fault. Consider MUZIC_FFMPEG_FORCE_SOFTWARE=1.",
                    "warn",
                )

            if run_duration >= 30.0:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    append_app_log(
                        f"channel {self.channel_id}: {consecutive_failures} consecutive short crashes "
                        f"(each <30s) — stopping channel to prevent restart loop. "
                        f"Fix the channel configuration and restart manually.",
                        "error",
                    )
                    break

            now = time.monotonic()
            delay = 3 if (self._last_restart_mono == 0 or (now - self._last_restart_mono) >= 120) else 15
            self._last_restart_mono = now

            append_app_log(
                f"channel {self.channel_id}: auto-restarting in {delay}s "
                f"(pts_offset={self.pts_offset:.1f}s, consecutive_failures={consecutive_failures})",
                "warn",
            )

            await asyncio.sleep(delay)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _kill_proc(self) -> None:
        proc = self._proc
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None

    async def _stop_np(self) -> None:
        if self._np_stop:
            self._np_stop.set()
        if self._np_task and not self._np_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._np_task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._np_stop = None
        self._np_task = None

    def _cleanup_hls_files(self) -> None:
        out_dir = settings.data_dir / "streams" / self.channel_id
        if not out_dir.is_dir():
            return
        cleaned = 0
        _overlay_names = {"art.png", "song.txt", "artist.txt", "bio.txt", "channel_name.txt"}
        for f in list(out_dir.iterdir()):
            if f.is_file() and (f.suffix in (".ts", ".tmp") or f.name == "index.m3u8" or f.name in _overlay_names):
                try:
                    f.unlink()
                    cleaned += 1
                except OSError:
                    pass
        if cleaned:
            append_app_log(f"channel {self.channel_id}: removed {cleaned} HLS file(s) after stop", "debug")

    async def _cleanup_stale_segments(self, state: AdminState) -> None:
        """Keep index.m3u8 and recent .ts files; delete only expired segments and .tmp files.

        Called before each auto-restart so in-flight conversion ffmpegs (serving
        Plex/Kodi) keep reading valid segments during the restart gap.
        """
        fs = state.ffmpeg_settings or FFmpegSettings()
        hls_time = max(1, min(30, fs.hls_time))
        hls_list = max(2, min(30, fs.hls_list_size))
        stale_before = time.time() - (hls_list * hls_time + 10)

        out_dir = settings.data_dir / "streams" / self.channel_id
        if not out_dir.is_dir():
            return
        cleaned = 0
        for f in list(out_dir.iterdir()):
            if not f.is_file():
                continue
            if f.suffix == ".tmp":
                try:
                    f.unlink()
                    cleaned += 1
                except OSError:
                    pass
            elif f.suffix == ".ts":
                try:
                    if f.stat().st_mtime < stale_before:
                        f.unlink()
                        cleaned += 1
                except OSError:
                    pass
        if cleaned:
            append_app_log(
                f"channel {self.channel_id}: removed {cleaned} expired segment(s) before auto-restart",
                "debug",
            )

    async def _launch_ffmpeg(
        self,
        state: AdminState,
        channel: Channel,
        clean_start: bool,
        pts_offset_secs: float,
    ) -> tuple[asyncio.subprocess.Process | None, bool]:
        """Build and launch the ffmpeg HLS encoding process.

        clean_start=True  — delete all old HLS files (first/user-initiated start).
        clean_start=False — keep files for in-flight clients (auto-restart path).
        pts_offset_secs   — -output_ts_offset value for PTS continuity on restart.
        """
        profile = _get_profile(state, channel.ffmpeg_profile_id)
        if not profile:
            return None, False

        fs = state.ffmpeg_settings if state.ffmpeg_settings is not None else FFmpegSettings()
        hls_time_sec = max(1, min(30, fs.hls_time))
        hls_list_size_val = max(2, min(30, fs.hls_list_size))
        ffmpeg_executable = (fs.ffmpeg_path or "ffmpeg").strip() or "ffmpeg"

        out_dir = settings.data_dir / "streams" / channel.id
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / "index.m3u8"

        if clean_start:
            cleaned = 0
            for _f in list(out_dir.iterdir()):
                if _f.is_file() and (_f.suffix in (".ts", ".tmp") or _f.name == "index.m3u8"):
                    try:
                        _f.unlink()
                        cleaned += 1
                    except OSError:
                        pass
            if cleaned:
                append_app_log(f"channel {channel.id}: removed {cleaned} stale HLS file(s) before start", "debug")

        bg_path: Path | None = None
        bid = (channel.background_id or "stock").strip()
        if bid and bid not in ("stock", "stock-dark"):
            try:
                from app.store import load_backgrounds
                bgs = await load_backgrounds()
                bg_t = next((b for b in bgs if b.id == bid), None)
                if bg_t and not bg_t.is_stock and bg_t.image_path:
                    root = settings.backgrounds_dir or settings.data_dir / "backgrounds"
                    custom = root / bg_t.image_path
                    if custom.exists():
                        bg_path = custom
                    else:
                        _log.warning("Channel %s: custom background not found: %s", channel.id, custom)
                elif not bg_t:
                    _log.warning("Channel %s: background_id=%r not found", channel.id, bid)
            except Exception as e:
                _log.warning("Channel %s: failed to resolve custom background: %s", channel.id, e)
        if bg_path is None:
            try:
                bg_path = ensure_stock_dark_background_png() if bid == "stock-dark" else ensure_stock_background_png()
            except Exception as e:
                _log.warning("Channel %s: stock background failed: %s", channel.id, e)

        placements = default_overlay_placements()
        placements_from_editor = False
        try:
            from app.store import load_backgrounds
            bgs = await load_backgrounds()
            if bid and bid not in ("stock", "stock-dark"):
                bg = next((b for b in bgs if b.id == bid), None)
                if bg and bg.overlay_placements:
                    placements = bg.overlay_placements
                    placements_from_editor = True
        except Exception:
            pass

        out_w = settings.output_width
        out_h = settings.output_height

        def _sx(x: int) -> int: return int(round(x * out_w / 1280))
        def _sy(y: int) -> int: return int(round(y * out_h / 720))
        def to_px_x(x: int) -> int: return int(x * out_w / 100) if placements_from_editor and x <= 100 else x
        def to_px_y(y: int) -> int: return int(y * out_h / 100) if placements_from_editor and y <= 100 else y
        def norm_color(c: str) -> str:
            c = (c or "white").strip()
            return ("0x" + c[1:]) if c.startswith("#") and len(c) in (4, 7, 9) else c
        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace("'", "'\\\\''").replace(":", "\\:")
        def overlay_hidden(pl) -> bool:
            return pl is not None and getattr(pl, "hidden", False)

        channel_name_pl = get_placement(placements, "channel_name")
        song_pl = get_placement(placements, "song_title") or (placements[0] if placements else None)
        artist_pl = get_placement(placements, "artist_name") or (placements[1] if len(placements) > 1 else None)
        bio_pl = get_placement(placements, "artist_bio")
        image_pl = get_placement(placements, "artist_image")

        ch_name_x = to_px_x(channel_name_pl.x) if channel_name_pl else _sx(27)
        ch_name_y = to_px_y(channel_name_pl.y) if channel_name_pl else _sy(27)
        ch_name_fs = (channel_name_pl.font_size if channel_name_pl and channel_name_pl.font_size else 26)
        ch_name_fc = norm_color(channel_name_pl.font_color) if channel_name_pl else "white"
        ch_name_sc = norm_color(channel_name_pl.shadow_color) if channel_name_pl else "black"
        song_x = to_px_x(song_pl.x) if song_pl else _sx(80)
        song_y = to_px_y(song_pl.y) if song_pl else _sy(520)
        song_fs = (song_pl.font_size if song_pl and song_pl.font_size else 32)
        song_fc = norm_color(song_pl.font_color) if song_pl else "white"
        song_sc = norm_color(song_pl.shadow_color) if song_pl else "black"
        artist_x = to_px_x(artist_pl.x) if artist_pl else _sx(80)
        artist_y = to_px_y(artist_pl.y) if artist_pl else _sy(598)
        artist_fs = (artist_pl.font_size if artist_pl and artist_pl.font_size else 28)
        artist_fc = norm_color(artist_pl.font_color) if artist_pl else "white"
        artist_sc = norm_color(artist_pl.shadow_color) if artist_pl else "black"
        bio_x = to_px_x(bio_pl.x) if bio_pl else _sx(435)
        bio_y = to_px_y(bio_pl.y) if bio_pl else _sy(250)
        bio_fs = (bio_pl.font_size if bio_pl and bio_pl.font_size else 26)
        bio_fc = norm_color(bio_pl.font_color) if bio_pl else "white"
        bio_sc = norm_color(bio_pl.shadow_color) if bio_pl else "black"

        display_name = (channel.name or _get_station_name(channel, state) or channel.slug or channel.id or "Channel").strip() or "—"
        channel_name_txt = out_dir / "channel_name.txt"
        channel_name_txt.write_text(display_name, encoding="utf-8")
        song_txt = out_dir / "song.txt"
        artist_txt = out_dir / "artist.txt"
        bio_txt = out_dir / "bio.txt"
        song_txt.write_text("—", encoding="utf-8")
        artist_txt.write_text("—", encoding="utf-8")
        bio_txt.write_text("—", encoding="utf-8")

        audio_url = _get_azuracast_listen_url(channel, state)

        cmd: list[str] = ["-y"]
        if not audio_url:
            cmd.append("-re")
        if getattr(profile, "thread_count", 0) and profile.thread_count > 0:
            cmd.extend(["-threads", str(profile.thread_count)])

        from app.config import settings as _cfg
        force_sw = getattr(_cfg, "ffmpeg_force_software", False)
        use_hw = profile.hardware_accel and profile.hw_accel_type != "none" and not force_sw

        if use_hw:
            append_app_log(f"Channel {channel.id}: using hardware encoding ({profile.hw_accel_type})", "info")
            if profile.hw_accel_type == "nvenc":
                video_codec = "h264_nvenc"
            elif profile.hw_accel_type == "vaapi":
                va_device = (profile.hw_accel_device or "").strip() or "/dev/dri/renderD128"
                cmd.extend(["-vaapi_device", va_device])
                video_codec = "h264_vaapi"
            elif profile.hw_accel_type == "qsv":
                if profile.hw_accel_device:
                    cmd.extend(["-hwaccel", "qsv", "-hwaccel_device", profile.hw_accel_device])
                else:
                    cmd.extend(["-hwaccel", "qsv"])
                cmd.extend(["-hwaccel_output_format", "qsv"])
                video_codec = "h264_qsv"
            elif profile.hw_accel_type == "videotoolbox":
                cmd.extend(["-hwaccel", "videotoolbox"])
                video_codec = "h264_videotoolbox"
            else:
                video_codec = profile.video_codec
        else:
            video_codec = profile.video_codec
            reason = "MUZIC_FFMPEG_FORCE_SOFTWARE=1" if force_sw else "profile has hardware_accel disabled"
            append_app_log(f"Channel {channel.id}: using software encoding ({reason})", "info")

        hw_upload = ",format=nv12,hwupload" if (use_hw and profile.hw_accel_type == "vaapi") else ""

        if audio_url:
            cmd.extend([
                "-reconnect", "1", "-reconnect_at_eof", "1",
                "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
                "-thread_queue_size", "128",
                "-i", audio_url,
            ])
            audio_input_index, video_input_index = 0, 1
        else:
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
            audio_input_index, video_input_index = 0, 1

        cn_path = esc(str(channel_name_txt))
        s_path = esc(str(song_txt))
        a_path = esc(str(artist_txt))
        b_path = esc(str(bio_txt))

        vf_parts = [f"scale={out_w}:{out_h}"]
        if not overlay_hidden(channel_name_pl):
            vf_parts.append(f"drawtext=textfile='{cn_path}':reload=1:x={ch_name_x}:y={ch_name_y}:fontsize={ch_name_fs}:fontcolor={esc(ch_name_fc)}:shadowcolor={esc(ch_name_sc)}:shadowx=1:shadowy=1")
        if not overlay_hidden(song_pl):
            vf_parts.append(f"drawtext=textfile='{s_path}':reload=1:x={song_x}:y={song_y}:fontsize={song_fs}:fontcolor={esc(song_fc)}:shadowcolor={esc(song_sc)}:shadowx=1:shadowy=1")
        if not overlay_hidden(artist_pl):
            vf_parts.append(f"drawtext=textfile='{a_path}':reload=1:x={artist_x}:y={artist_y}:fontsize={artist_fs}:fontcolor={esc(artist_fc)}:shadowcolor={esc(artist_sc)}:shadowx=1:shadowy=1")
        if bio_pl and not overlay_hidden(bio_pl):
            vf_parts.append(f"drawtext=textfile='{b_path}':reload=1:x={bio_x}:y={bio_y}:fontsize={bio_fs}:fontcolor={esc(bio_fc)}:shadowcolor={esc(bio_sc)}:shadowx=1:shadowy=1:line_spacing=4")
        vf = ",".join(vf_parts)

        art_path = out_dir / "art.png"
        art_ready = art_path.exists() and art_path.stat().st_size > 0
        image_visible = image_pl and not overlay_hidden(image_pl)
        if image_pl and not art_ready:
            try:
                from app.now_playing import _default_art_path, _ensure_placeholder_art
                default_art = _default_art_path()
                if default_art:
                    import shutil
                    shutil.copy2(default_art, art_path)
                    append_metadata_log(channel.id, "Art at startup: using default icon")
                else:
                    _ensure_placeholder_art(art_path)
                    append_metadata_log(channel.id, "Art at startup: using placeholder")
            except Exception as e:
                _log.warning("Channel %s: art placeholder failed: %s", channel.id, e)
        elif image_pl and art_ready:
            try:
                append_metadata_log(channel.id, f"Art at startup: art.png ({art_path.stat().st_size} bytes)")
            except Exception:
                pass

        def _art_dims():
            art_w = int(image_pl.width * out_w / 100) if placements_from_editor and image_pl.width and image_pl.width <= 100 else (image_pl.width or 230)
            art_h = int(image_pl.height * out_h / 100) if placements_from_editor and image_pl.height and image_pl.height <= 100 else (image_pl.height or 230)
            art_x = to_px_x(image_pl.x) if image_pl.x is not None else 40
            art_y = to_px_y(image_pl.y) if image_pl.y is not None else 140
            return max(40, min(art_w, out_w)), max(40, min(art_h, out_h)), art_x, art_y

        if bg_path and bg_path.exists():
            cmd.extend(["-loop", "1", "-framerate", "25", "-i", str(bg_path)])
            if art_path.exists() and image_visible:
                aw, ah, ax, ay = _art_dims()
                cmd.extend(["-f", "image2", "-stream_loop", "-1", "-framerate", "1", "-i", str(art_path)])
                cmd.extend(["-filter_complex", f"[1:v]{vf}[vbase];[2:v]scale={aw}:{ah},format=rgba[art];[vbase][art]overlay={ax}:{ay},format=yuv420p{hw_upload}[vout]"])
                video_map = "[vout]"
            else:
                cmd.extend(["-vf", vf + hw_upload])
                video_map = f"{video_input_index}:v:0"
        else:
            if bg_path is None:
                _log.warning("Channel %s: no background (bid=%r); using solid color.", channel.id, bid)
            else:
                _log.warning("Channel %s: background missing: %s; using solid color.", channel.id, bg_path)
            cmd.append("-re")
            color_src = f"color=c=0x1e3a5f:s={out_w}x{out_h}:r=25" + (":format=yuv420p" if use_hw and profile.hw_accel_type in ("vaapi", "qsv") else "")
            cmd.extend(["-f", "lavfi", "-i", color_src])
            if art_path.exists() and image_visible:
                aw, ah, ax, ay = _art_dims()
                cmd.extend(["-f", "image2", "-stream_loop", "-1", "-framerate", "1", "-i", str(art_path)])
                cmd.extend(["-filter_complex", f"[1:v]{vf}[vbase];[2:v]scale={aw}:{ah},format=rgba[art];[vbase][art]overlay={ax}:{ay},format=yuv420p{hw_upload}[vout]"])
                video_map = "[vout]"
            else:
                cmd.extend(["-vf", vf + hw_upload])
                video_map = f"{video_input_index}:v:0"

        fps = 25
        gop_size = fps * hls_time_sec
        cmd.extend([
            "-shortest",
            "-avoid_negative_ts", "make_zero",
            "-map", video_map,
            "-map", f"{audio_input_index}:a:0",
            "-c:v", video_codec,
            "-b:v", profile.video_bitrate,
        ])
        if getattr(profile, "video_buffer_size", "") and (profile.video_buffer_size or "").strip():
            cmd.extend(["-bufsize", profile.video_buffer_size.strip()])
        if use_hw and profile.hw_accel_type == "nvenc" and not getattr(profile, "allow_bframes", True):
            cmd.extend(["-bf", "0"])
        elif not use_hw and video_codec == "libx264":
            if getattr(profile, "video_profile", "") and (profile.video_profile or "").strip():
                cmd.extend(["-profile:v", profile.video_profile.strip()])
            if not getattr(profile, "allow_bframes", True):
                cmd.extend(["-bf", "0"])
        cmd.extend([
            "-g", str(gop_size),
            "-keyint_min", str(gop_size),
            "-force_key_frames", f"expr:gte(t,n_forced*{hls_time_sec})",
        ])
        if not use_hw:
            cmd.extend(["-preset", profile.preset])
        elif profile.hw_accel_type == "nvenc":
            nvenc_map = {"ultrafast": "p1", "superfast": "p2", "veryfast": "p3", "faster": "p4",
                         "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p6", "veryslow": "p7"}
            cmd.extend(["-preset", nvenc_map.get((profile.preset or "medium").lower(), "p4")])
        elif profile.hw_accel_type == "vaapi":
            cmd.extend(["-qp", "23"])
        elif profile.hw_accel_type == "qsv":
            qsv_map = {"ultrafast": "veryfast", "superfast": "veryfast", "veryfast": "veryfast",
                       "faster": "faster", "fast": "fast", "medium": "medium", "slow": "slow",
                       "slower": "slower", "veryslow": "veryslow"}
            cmd.extend(["-preset", qsv_map.get((profile.preset or "medium").lower(), "medium")])
        elif profile.hw_accel_type == "videotoolbox":
            cmd.extend(["-allow_sw", "1"])

        if not use_hw:
            cmd.extend(["-pix_fmt", profile.pixel_format])
        elif profile.hw_accel_type == "videotoolbox":
            cmd.extend(["-pix_fmt", profile.pixel_format])

        cmd.extend(["-c:a", profile.audio_codec, "-b:a", profile.audio_bitrate])
        if getattr(profile, "audio_channels", 0) and profile.audio_channels > 0:
            cmd.extend(["-ac", str(profile.audio_channels)])
        if getattr(profile, "sample_rate", "") and (profile.sample_rate or "").strip():
            cmd.extend(["-ar", profile.sample_rate.strip()])

        seg_filename = str(out_dir / "seg%d.ts")
        if pts_offset_secs > 0:
            cmd.extend(["-output_ts_offset", f"{pts_offset_secs:.3f}"])
        cmd.extend([
            "-f", "hls",
            "-hls_segment_type", "mpegts",
            "-hls_time", str(hls_time_sec),
            "-hls_list_size", str(hls_list_size_val),
            "-hls_flags", "delete_segments+program_date_time+omit_endlist+independent_segments+discont_start",
            "-hls_delete_threshold", "3",
            "-hls_allow_cache", "0",
            "-hls_start_number_source", "epoch",
            "-hls_segment_filename", seg_filename,
            str(output_path),
        ])
        cmd.extend(profile.extra_args)

        listeners = self.log_listeners

        def _log_cb(line: str) -> None:
            for fn in listeners:
                try:
                    fn(line)
                except Exception:
                    pass

        preview = " ".join([ffmpeg_executable] + cmd[:12]) + (" ..." if len(cmd) > 12 else "")
        append_app_log(f"channel {channel.id}: launching ffmpeg cmd: {preview}", "debug")

        proc = await start_channel_ffmpeg(channel.id, cmd, on_log=_log_cb, ffmpeg_executable=ffmpeg_executable)
        if not proc:
            return None, False

        await self._stop_np()
        stop_ev = asyncio.Event()
        self._np_stop = stop_ev

        async def _prefetch(_ch=channel, _st=state, _dir=out_dir):
            try:
                await asyncio.wait_for(write_now_playing_files(_dir, _ch, _st), timeout=10.0)
            except Exception:
                pass

        asyncio.create_task(_prefetch())
        self._np_task = asyncio.create_task(
            now_playing_loop(channel.id, out_dir, load_admin_state, 10.0, stop_ev, on_song_change=None)
        )

        self._last_activity = time.time()
        return proc, use_hw
