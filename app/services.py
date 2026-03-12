"""Channel streaming service: start/stop all channels, track processes."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable

from app.config import settings
from app.ffmpeg_runner import start_channel_ffmpeg, append_app_log, append_metadata_log
from app.models import AdminState, Channel, FFmpegProfile, FFmpegSettings
from app.store import load_admin_state
from app.overlay import (
    default_overlay_placements,
    ensure_stock_background_png,
    ensure_stock_dark_background_png,
    get_placement,
)
from app.now_playing import now_playing_loop, write_now_playing_files


_running: dict[str, asyncio.subprocess.Process] = {}
_now_playing_stop: dict[str, asyncio.Event] = {}
_now_playing_tasks: dict[str, asyncio.Task] = {}
_watch_tasks: dict[str, asyncio.Task] = {}
_stop_requested: set[str] = set()
_user_stopped: set[str] = set()
_starting: set[str] = set()
_log_listeners: dict[str, list[Callable[[str], None]]] = {}
_last_auto_restart_time: dict[str, float] = {}
_channel_started_at: dict[str, float] = {}


def _cleanup_hls_files(channel_id: str) -> None:
    """Delete HLS segments and playlist for a channel so stale content is not served."""
    out_dir = settings.data_dir / "streams" / channel_id
    if not out_dir.is_dir():
        return
    cleaned = 0
    for f in list(out_dir.iterdir()):
        if f.is_file() and (f.suffix in (".ts", ".tmp") or f.name == "index.m3u8"):
            try:
                f.unlink()
                cleaned += 1
            except OSError:
                pass
    if cleaned:
        append_app_log(f"channel {channel_id}: removed {cleaned} HLS file(s) after stop", "debug")


def _get_profile(state: AdminState, profile_id: str) -> FFmpegProfile | None:
    if not (profile_id or "").strip():
        return state.ffmpeg_profiles[0] if state.ffmpeg_profiles else None
    pid = (profile_id or "").strip()
    for p in state.ffmpeg_profiles:
        if (getattr(p, "id", None) or "").strip() == pid or (p.name or "").strip() == pid:
            return p
    return state.ffmpeg_profiles[0] if state.ffmpeg_profiles else None


async def _watch_ffmpeg_exit(channel_id: str, proc: asyncio.subprocess.Process, used_hw_accel: bool = False) -> None:
    """Wait for FFmpeg process to exit; if it was not a requested stop, log and auto-restart once after delay."""
    try:
        returncode = await proc.wait()
        _running.pop(channel_id, None)
        _stop_now_playing(channel_id)
        np_task = _now_playing_tasks.pop(channel_id, None)
        if np_task and not np_task.done():
            np_task.cancel()
            try:
                await np_task
            except asyncio.CancelledError:
                pass
        _now_playing_stop.pop(channel_id, None)
        _watch_tasks.pop(channel_id, None)

        if channel_id in _stop_requested or channel_id in _user_stopped:
            _stop_requested.discard(channel_id)
            append_app_log(f"channel {channel_id}: FFmpeg exited (code={returncode}) — stop was requested, no restart", "debug")
            return

        append_app_log(f"channel {channel_id}: FFmpeg process exited with code {returncode}", "debug")
        now = time.monotonic()
        delay = 15
        if channel_id in _last_auto_restart_time and (now - _last_auto_restart_time[channel_id]) < 120:
            delay = 60
        append_app_log(f"channel {channel_id} FFmpeg exited unexpectedly (code={returncode}). Will auto-restart in {delay}s.", "warn")
        if returncode != 0 and used_hw_accel:
            append_app_log(f"channel {channel_id} was using hardware encoding; exit may be due to GPU/accel failure. Consider software encoding or MUZIC_FFMPEG_FORCE_SOFTWARE=1.", "warn")
        await asyncio.sleep(delay)
        if channel_id in _running:
            append_app_log(f"channel {channel_id}: skip auto-restart — channel already running again", "debug")
            return
        if channel_id in _stop_requested or channel_id in _user_stopped:
            _stop_requested.discard(channel_id)
            append_app_log(f"channel {channel_id}: skip auto-restart — channel is in user-stopped or stop-requested set", "debug")
            return
        state = await load_admin_state()
        if not getattr(state, "service_started", False):
            append_app_log(f"channel {channel_id}: skip auto-restart — service is stopped", "debug")
            return
        ch = next((c for c in state.channels if c.id == channel_id), None)
        if not ch or not ch.enabled:
            append_app_log(f"channel {channel_id}: skip auto-restart — channel not found or disabled", "debug")
            return
        _last_auto_restart_time[channel_id] = time.monotonic()
        append_app_log(f"channel {channel_id} auto-restarting after unexpected exit.", "warn")
        result = await _start_single_channel(ch, state, index=0)
        if result == "ok":
            append_app_log(f"channel {channel_id} auto-restart succeeded.")
        else:
            append_app_log(f"channel {channel_id} auto-restart failed: {result}", "error")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        append_app_log(f"channel {channel_id} watch task error: {e}", "error")


async def start_all_channels() -> dict[str, str]:
    """Start FFmpeg for all enabled channels. Returns {channel_id: "ok"|"error"}."""
    _last_auto_restart_time.clear()
    state = await load_admin_state()
    results: dict[str, str] = {}
    for i, ch in enumerate(state.channels):
        if not ch.enabled:
            continue
        results[ch.id] = await _start_single_channel(ch, state, index=i)
    return results


def _stop_now_playing(channel_id: str) -> None:
    """Signal the now-playing loop to exit."""
    ev = _now_playing_stop.get(channel_id)
    if ev:
        ev.set()


async def stop_all_channels() -> None:
    """Stop all running channel processes and now-playing tasks."""
    running_ids = list(_running.keys())
    if running_ids:
        append_app_log(f"stopping all channels: {running_ids}", "debug")
    _stop_requested.update(_running.keys())
    for cid in list(_running.keys()):
        _stop_now_playing(cid)
    for cid, proc in list(_running.items()):
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _running.pop(cid, None)
    tasks = [t for t in _now_playing_tasks.values() if not t.done()]
    if tasks:
        await asyncio.wait(tasks, timeout=3.0, return_when=asyncio.ALL_COMPLETED)
    _now_playing_tasks.clear()
    _now_playing_stop.clear()
    _watch_tasks.clear()
    _stop_requested.clear()
    # _user_stopped intentionally NOT cleared — per-channel stop intent must survive service stop/restart


async def stop_channel(channel_id: str) -> None:
    """Stop a single channel if running."""
    _stop_requested.add(channel_id)
    _stop_now_playing(channel_id)
    proc = _running.get(channel_id)
    if not proc:
        _now_playing_stop.pop(channel_id, None)
        _now_playing_tasks.pop(channel_id, None)
        watch = _watch_tasks.pop(channel_id, None)
        if watch and not watch.done():
            watch.cancel()
            try:
                await watch
            except asyncio.CancelledError:
                pass
            _stop_requested.discard(channel_id)
        elif watch is None:
            pass
        else:
            _stop_requested.discard(channel_id)
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    _running.pop(channel_id, None)
    _channel_started_at.pop(channel_id, None)
    task = _now_playing_tasks.pop(channel_id, None)
    if task and not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    _now_playing_stop.pop(channel_id, None)
    _stop_requested.discard(channel_id)
    watch = _watch_tasks.pop(channel_id, None)
    if watch and not watch.done():
        watch.cancel()
        try:
            await watch
        except asyncio.CancelledError:
            pass
    _cleanup_hls_files(channel_id)
    append_app_log(f"channel {channel_id} stopped", "info")


async def start_channel(channel_id: str) -> str:
    """Start FFmpeg for a single channel (if not already running).
    Uses _starting guard to prevent concurrent calls from launching two FFmpeg processes."""
    if channel_id in _user_stopped:
        append_app_log(f"channel {channel_id}: cleared from user-stopped set (explicit start)", "debug")
    _user_stopped.discard(channel_id)
    if is_running(channel_id):
        return "ok"
    if channel_id in _starting:
        return "ok"
    _starting.add(channel_id)
    try:
        if is_running(channel_id):
            return "ok"
        state = await load_admin_state()
        ch = next((c for c in state.channels if c.id == channel_id), None)
        if not ch:
            append_app_log(f"channel {channel_id} start failed: not found", "error")
            return "error: channel not found"
        if not ch.enabled:
            append_app_log(f"channel {channel_id} start failed: disabled", "error")
            return "error: channel disabled"
        result = await _start_single_channel(ch, state, index=0)
        if result == "ok":
            append_app_log(f"channel {channel_id} started", "info")
        else:
            append_app_log(f"channel {channel_id} start failed: {result}", "error")
        return result
    finally:
        _starting.discard(channel_id)


async def stop_channel_api(channel_id: str, grace: bool = False) -> str:
    """Stop a single channel. Returns 'ok' or error string.
    grace=True means the stop was triggered by the client navigating away (not an explicit user action),
    so the channel should NOT be added to _user_stopped and can be freely restarted.
    If an auto-stop (_stop_requested) is already in progress, the channel is NOT added to _user_stopped
    to avoid locking the channel when the user clicks Stop during the idle-shutdown window."""
    if not is_running(channel_id):
        append_app_log(f"channel {channel_id}: stop_channel_api called but not running", "debug")
        return "ok"
    if not grace:
        if channel_id in _stop_requested:
            append_app_log(f"channel {channel_id}: auto-stop already in progress — not adding to user-stopped set", "debug")
        else:
            _user_stopped.add(channel_id)
            append_app_log(f"channel {channel_id}: added to user-stopped set", "debug")
    await stop_channel(channel_id)
    return "ok"


async def restart_channel(channel_id: str) -> str:
    """Restart FFmpeg for a single channel."""
    await stop_channel(channel_id)
    state = await load_admin_state()
    ch = next((c for c in state.channels if c.id == channel_id), None)
    if not ch:
        return "error: channel not found"
    if not ch.enabled:
        return "error: channel disabled"
    result = await _start_single_channel(ch, state, index=0)
    if result == "ok":
        append_app_log(f"channel {channel_id} restarted", "info")
    return result


def is_running(channel_id: str) -> bool:
    return channel_id in _running


async def ensure_channel_running(channel_id: str) -> bool:
    """Start the channel if not running and the service is enabled. Returns True if running."""
    state = await load_admin_state()
    if not getattr(state, "service_started", False):
        return False
    ch = next((c for c in (state.channels or []) if c.id == channel_id), None)
    if not ch or not ch.enabled:
        return False
    if is_running(channel_id):
        return True
    result = await start_channel(channel_id)
    return result == "ok"


def notify_stream_request(channel_id: str) -> None:
    """Called when a stream request arrives for a channel — resets the idle timer."""
    _channel_started_at[channel_id] = time.time()


def subscribe_logs(channel_id: str, callback: Callable[[str], None]) -> Callable[[], None]:
    """Subscribe to live logs for a channel. Returns unsubscribe fn."""
    if channel_id not in _log_listeners:
        _log_listeners[channel_id] = []
    _log_listeners[channel_id].append(callback)

    def unsub() -> None:
        _log_listeners.get(channel_id, []).remove(callback)
    return unsub


def get_running_channel_ids() -> list[str]:
    return list(_running.keys())


def _get_station_name_for_channel(channel: Channel, state: AdminState) -> str:
    """Resolve channel's Azuracast station to its display name (for default channel name)."""
    want = (channel.azuracast_station_id or "").strip()
    if not want:
        return ""
    for st in state.azuracast_stations:
        if (st.name or "").strip() == want or (st.station_shortcode or "").strip() == want:
            return (st.name or "").strip() or (st.station_shortcode or "").strip()
    return ""


def _get_azuracast_listen_url(channel: Channel, state: AdminState) -> str | None:
    """Resolve channel's Azuracast station to the listen stream URL (e.g. .../listen/station_slug/radio.mp3)."""
    want = (channel.azuracast_station_id or "").strip()
    if not want:
        return None
    for st in state.azuracast_stations:
        name = (st.name or "").strip()
        shortcode = (st.station_shortcode or "").strip()
        if not st.base_url or not shortcode:
            continue
        if name == want or shortcode == want:
            base = st.base_url.rstrip("/")
            return f"{base}/listen/{shortcode}/radio.mp3"
    return None


def _get_ffmpeg_settings(state: AdminState) -> FFmpegSettings:
    """Return FFmpeg settings from state or defaults."""
    if state.ffmpeg_settings is not None:
        return state.ffmpeg_settings
    return FFmpegSettings()


async def _start_single_channel(channel: Channel, state: AdminState, index: int) -> str:
    """Internal helper to start one channel HLS pipeline with background + overlay."""
    _stop_requested.discard(channel.id)
    profile = _get_profile(state, channel.ffmpeg_profile_id)
    if not profile:
        return "error: no ffmpeg profile"

    ff_settings = _get_ffmpeg_settings(state)
    hls_time_sec = max(1, min(30, ff_settings.hls_time))
    hls_list_size_val = max(2, min(30, ff_settings.hls_list_size))
    ffmpeg_executable = (ff_settings.ffmpeg_path or "ffmpeg").strip() or "ffmpeg"

    streams_root = settings.data_dir / "streams"
    out_dir: Path = streams_root / channel.id
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "index.m3u8"

    _cleaned = 0
    for _f in list(out_dir.iterdir()):
        if _f.is_file() and (_f.suffix in (".ts", ".tmp") or _f.name == "index.m3u8"):
            try:
                _f.unlink()
                _cleaned += 1
            except OSError:
                pass
    if _cleaned:
        append_app_log(f"channel {channel.id}: removed {_cleaned} stale HLS segment(s) before start", "debug")

    bg_path: Path | None = None
    bid = (channel.background_id or "stock").strip()
    _log = logging.getLogger("app.services")
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
                    _log.warning("Channel %s: custom background file not found: %s", channel.id, custom)
            elif not bg_t:
                _log.warning("Channel %s: background_id=%r not found in store", channel.id, bid)
        except Exception as e:
            _log.warning("Channel %s: failed to resolve custom background: %s", channel.id, e)
    if bg_path is None:
        try:
            if bid == "stock-dark":
                bg_path = ensure_stock_dark_background_png()
            else:
                bg_path = ensure_stock_background_png()
        except Exception as e:
            _log.warning("Channel %s: stock background failed: %s", channel.id, e)
            bg_path = None

    placements = default_overlay_placements()
    placements_from_editor = False
    try:
        from app.store import load_backgrounds
        bgs = await load_backgrounds()
        bid = (channel.background_id or "stock").strip()
        if bid and bid not in ("stock", "stock-dark"):
            bg = next((b for b in bgs if b.id == bid), None)
            if bg and bg.overlay_placements:
                placements = bg.overlay_placements
                placements_from_editor = True
    except Exception:
        pass

    out_w = settings.output_width
    out_h = settings.output_height

    def _sx(x: int) -> int:
        return int(round(x * out_w / 1280))
    def _sy(y: int) -> int:
        return int(round(y * out_h / 720))

    def to_px_x(x: int) -> int:
        return int(x * out_w / 100) if placements_from_editor and x <= 100 else x

    def to_px_y(y: int) -> int:
        return int(y * out_h / 100) if placements_from_editor and y <= 100 else y

    def norm_color(c: str) -> str:
        c = (c or "white").strip()
        if c.startswith("#") and len(c) in (4, 7, 9):
            return "0x" + c[1:]
        return c

    channel_name_pl = get_placement(placements, "channel_name")
    song_pl = get_placement(placements, "song_title") or (placements[0] if placements else None)
    artist_pl = get_placement(placements, "artist_name") or (placements[1] if len(placements) > 1 else None)
    bio_pl = get_placement(placements, "artist_bio")
    image_pl = get_placement(placements, "artist_image")
    # Fallbacks in output-resolution pixels (1280×720 base)
    ch_name_x = to_px_x(channel_name_pl.x) if channel_name_pl else _sx(27)
    ch_name_y = to_px_y(channel_name_pl.y) if channel_name_pl else _sy(27)
    ch_name_fs = channel_name_pl.font_size if channel_name_pl and channel_name_pl.font_size else 26
    ch_name_fc = norm_color(channel_name_pl.font_color) if channel_name_pl else "white"
    ch_name_sc = norm_color(channel_name_pl.shadow_color) if channel_name_pl else "black"
    song_x = to_px_x(song_pl.x) if song_pl else _sx(80)
    song_y = to_px_y(song_pl.y) if song_pl else _sy(520)
    song_fs = song_pl.font_size if song_pl and song_pl.font_size else 32
    song_fc = norm_color(song_pl.font_color) if song_pl else "white"
    song_sc = norm_color(song_pl.shadow_color) if song_pl else "black"
    artist_x = to_px_x(artist_pl.x) if artist_pl else _sx(80)
    artist_y = to_px_y(artist_pl.y) if artist_pl else _sy(598)
    artist_fs = artist_pl.font_size if artist_pl and artist_pl.font_size else 28
    artist_fc = norm_color(artist_pl.font_color) if artist_pl else "white"
    artist_sc = norm_color(artist_pl.shadow_color) if artist_pl else "black"
    bio_x_default = _sx(435)
    bio_y_default = _sy(250)
    bio_fs_default = 26
    try:
        await asyncio.wait_for(write_now_playing_files(out_dir, channel, state), timeout=10.0)
    except asyncio.TimeoutError:
        append_app_log(f"channel {channel.id}: metadata fetch timed out at startup — using placeholders", "warn")
    channel_name_txt = out_dir / "channel_name.txt"
    display_name = (channel.name or _get_station_name_for_channel(channel, state) or channel.slug or channel.id or "Channel").strip() or "—"
    channel_name_txt.write_text(display_name, encoding="utf-8")
    song_txt = out_dir / "song.txt"
    artist_txt = out_dir / "artist.txt"
    bio_txt = out_dir / "bio.txt"
    if not song_txt.exists():
        song_txt.write_text("—", encoding="utf-8")
    if not artist_txt.exists():
        artist_txt.write_text("—", encoding="utf-8")
    if not bio_txt.exists():
        bio_txt.write_text("—", encoding="utf-8")

    audio_url = _get_azuracast_listen_url(channel, state)

    cmd = ["-y"]
    if not audio_url:
        cmd.append("-re")
    if getattr(profile, "thread_count", 0) and profile.thread_count > 0:
        cmd.extend(["-threads", str(profile.thread_count)])

    from app.config import settings as _settings
    from app.ffmpeg_runner import append_app_log
    force_sw = getattr(_settings, "ffmpeg_force_software", False)
    use_hw = profile.hardware_accel and profile.hw_accel_type != "none" and not force_sw
    if use_hw:
        try:
            append_app_log(f"Channel {channel.id}: using hardware encoding ({profile.hw_accel_type})", "info")
        except Exception:
            pass
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
        try:
            if force_sw:
                append_app_log(f"Channel {channel.id}: using software encoding (MUZIC_FFMPEG_FORCE_SOFTWARE=1 or hardware disabled)", "info")
            else:
                append_app_log(f"Channel {channel.id}: using software encoding (profile has hardware_accel disabled)", "info")
        except Exception:
            pass

    hw_upload = ",format=nv12,hwupload" if (use_hw and profile.hw_accel_type == "vaapi") else ""

    if audio_url:
        cmd.extend([
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-thread_queue_size", "1024",
            "-i", audio_url,
        ])
        audio_input_index = 0
        video_input_index = 1
    else:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
        audio_input_index = 0
        video_input_index = 1

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("'", "'\\\\''").replace(":", "\\:")
    cn_path = esc(str(channel_name_txt))
    ch_name_fc_esc = esc(ch_name_fc)
    ch_name_sc_esc = esc(ch_name_sc)
    s_path = esc(str(song_txt))
    a_path = esc(str(artist_txt))
    b_path = esc(str(bio_txt))
    song_fc_esc = esc(song_fc)
    song_sc_esc = esc(song_sc)
    artist_fc_esc = esc(artist_fc)
    artist_sc_esc = esc(artist_sc)
    bio_x = to_px_x(bio_pl.x) if bio_pl else bio_x_default
    bio_y = to_px_y(bio_pl.y) if bio_pl else bio_y_default
    bio_fs = bio_pl.font_size if bio_pl and bio_pl.font_size else bio_fs_default
    bio_fc = norm_color(bio_pl.font_color) if bio_pl else "white"
    bio_sc = norm_color(bio_pl.shadow_color) if bio_pl else "black"
    bio_fc_esc = esc(bio_fc)
    bio_sc_esc = esc(bio_sc)
    song_x_param = f"x={song_x}"
    artist_x_param = f"x={artist_x}"
    bio_x_param = f"x={bio_x}"
    def overlay_hidden(pl) -> bool:
        return pl is not None and getattr(pl, "hidden", False)
    vf_parts = [f"scale={out_w}:{out_h}"]
    if not overlay_hidden(channel_name_pl):
        vf_parts.append(f"drawtext=textfile='{cn_path}':reload=1:x={ch_name_x}:y={ch_name_y}:fontsize={ch_name_fs}:fontcolor={ch_name_fc_esc}:shadowcolor={ch_name_sc_esc}:shadowx=1:shadowy=1")
    if not overlay_hidden(song_pl):
        vf_parts.append(f"drawtext=textfile='{s_path}':reload=1:{song_x_param}:y={song_y}:fontsize={song_fs}:fontcolor={song_fc_esc}:shadowcolor={song_sc_esc}:shadowx=1:shadowy=1")
    if not overlay_hidden(artist_pl):
        vf_parts.append(f"drawtext=textfile='{a_path}':reload=1:{artist_x_param}:y={artist_y}:fontsize={artist_fs}:fontcolor={artist_fc_esc}:shadowcolor={artist_sc_esc}:shadowx=1:shadowy=1")
    if bio_pl and not overlay_hidden(bio_pl):
        vf_parts.append(f"drawtext=textfile='{b_path}':reload=1:{bio_x_param}:y={bio_y}:fontsize={bio_fs}:fontcolor={bio_fc_esc}:shadowcolor={bio_sc_esc}:shadowx=1:shadowy=1:line_spacing=4")
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
                try:
                    append_metadata_log(channel.id, "Art at startup: no image, using default icon")
                except Exception:
                    pass
            else:
                _ensure_placeholder_art(art_path)
                try:
                    append_metadata_log(channel.id, "Art at startup: no image, using placeholder")
                except Exception:
                    pass
        except Exception as e:
            _log.warning("Channel %s: failed to create art placeholder: %s", channel.id, e)
    elif image_pl and art_ready:
        try:
            append_metadata_log(channel.id, f"Art at startup: art.png ({art_path.stat().st_size} bytes)")
        except Exception:
            pass

    if bg_path and bg_path.exists():
        _log.debug("Channel %s using background: %s", channel.id, bg_path)
        cmd.extend(["-loop", "1", "-framerate", "25", "-i", str(bg_path)])
        if art_path.exists() and image_visible:
            art_w = int(image_pl.width * out_w / 100) if placements_from_editor and image_pl.width and image_pl.width <= 100 else (image_pl.width or 230)
            art_h = int(image_pl.height * out_h / 100) if placements_from_editor and image_pl.height and image_pl.height <= 100 else (image_pl.height or 230)
            art_w = max(40, min(art_w, out_w))
            art_h = max(40, min(art_h, out_h))
            art_x = to_px_x(image_pl.x) if image_pl.x is not None else 40
            art_y = to_px_y(image_pl.y) if image_pl.y is not None else 140
            cmd.extend(["-f", "image2", "-stream_loop", "-1", "-framerate", "1", "-i", str(art_path)])
            fc = f"[1:v]{vf}[vbase];[2:v]scale={art_w}:{art_h},format=rgba[art];[vbase][art]overlay={art_x}:{art_y},format=yuv420p{hw_upload}[vout]"
            cmd.extend(["-filter_complex", fc])
            video_map = "[vout]"
        else:
            cmd.extend(["-vf", vf + hw_upload])
            video_map = f"{video_input_index}:v:0"
    else:
        if bg_path is None:
            _log.warning("Channel %s: no background path (bid=%r); using solid color.", channel.id, bid)
        else:
            _log.warning("Channel %s: background file missing: %s; using solid color.", channel.id, bg_path)
        cmd.append("-re")
        if use_hw and profile.hw_accel_type in ("vaapi", "qsv"):
            cmd.extend(["-f", "lavfi", "-i", f"color=c=0x1e3a5f:s={out_w}x{out_h}:r=25:format=yuv420p"])
        else:
            cmd.extend(["-f", "lavfi", "-i", f"color=c=0x1e3a5f:s={out_w}x{out_h}:r=25"])
        if art_path.exists() and image_visible:
            art_w = int(image_pl.width * out_w / 100) if placements_from_editor and image_pl.width and image_pl.width <= 100 else (image_pl.width or 230)
            art_h = int(image_pl.height * out_h / 100) if placements_from_editor and image_pl.height and image_pl.height <= 100 else (image_pl.height or 230)
            art_w = max(40, min(art_w, out_w))
            art_h = max(40, min(art_h, out_h))
            art_x = to_px_x(image_pl.x) if image_pl.x is not None else 40
            art_y = to_px_y(image_pl.y) if image_pl.y is not None else 140
            cmd.extend(["-f", "image2", "-stream_loop", "-1", "-framerate", "1", "-i", str(art_path)])
            fc = f"[1:v]{vf}[vbase];[2:v]scale={art_w}:{art_h},format=rgba[art];[vbase][art]overlay={art_x}:{art_y},format=yuv420p{hw_upload}[vout]"
            cmd.extend(["-filter_complex", fc])
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
        cmd.extend(["-bufsize", (profile.video_buffer_size or "").strip()])
    if use_hw and profile.hw_accel_type == "nvenc" and not getattr(profile, "allow_bframes", True):
        cmd.extend(["-bf", "0"])
    elif not use_hw and video_codec == "libx264":
        if getattr(profile, "video_profile", "") and (profile.video_profile or "").strip():
            cmd.extend(["-profile:v", (profile.video_profile or "").strip()])
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
        _nvenc_preset = {
            "ultrafast": "p1", "superfast": "p2", "veryfast": "p3", "faster": "p4", "fast": "p4",
            "medium": "p5", "slow": "p6", "slower": "p6", "veryslow": "p7", "custom": "p4",
        }.get((profile.preset or "medium").lower(), "p4")
        cmd.extend(["-preset", _nvenc_preset])
    elif profile.hw_accel_type == "vaapi":
        cmd.extend(["-qp", "23"])
    elif profile.hw_accel_type == "qsv":
        _qsv_preset = {
            "ultrafast": "veryfast", "superfast": "veryfast", "veryfast": "veryfast", "faster": "faster",
            "fast": "fast", "medium": "medium", "slow": "slow", "slower": "slower", "veryslow": "veryslow", "custom": "medium",
        }.get((profile.preset or "medium").lower(), "medium")
        cmd.extend(["-preset", _qsv_preset])
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
        cmd.extend(["-ar", (profile.sample_rate or "").strip()])
    seg_filename = str(out_dir / "seg%d.ts")
    cmd.extend([
        "-f", "hls",
        "-hls_segment_type", "mpegts",
        "-hls_time", str(hls_time_sec),
        "-hls_list_size", str(hls_list_size_val),
        "-hls_flags", "delete_segments+program_date_time+omit_endlist+independent_segments",
        "-hls_delete_threshold", "3",
        "-hls_allow_cache", "0",
        "-hls_segment_filename", seg_filename,
        str(output_path),
    ])
    cmd.extend(profile.extra_args)

    def make_cb(cid: str):
        def cb(line: str) -> None:
            for fn in _log_listeners.get(cid, []):
                try:
                    fn(line)
                except Exception:
                    pass

        return cb

    _cmd_preview = " ".join([ffmpeg_executable] + cmd[:12]) + (" ..." if len(cmd) > 12 else "")
    append_app_log(f"channel {channel.id}: launching ffmpeg cmd: {_cmd_preview}", "debug")
    proc = await start_channel_ffmpeg(
        channel.id, cmd, on_log=make_cb(channel.id), ffmpeg_executable=ffmpeg_executable
    )
    if proc:
        _running[channel.id] = proc
        _channel_started_at[channel.id] = time.time()
        stop_ev = asyncio.Event()
        _now_playing_stop[channel.id] = stop_ev
        task = asyncio.create_task(
            now_playing_loop(channel.id, out_dir, load_admin_state, 10.0, stop_ev, on_song_change=None)
        )
        _now_playing_tasks[channel.id] = task
        watch_task = asyncio.create_task(_watch_ffmpeg_exit(channel.id, proc, use_hw))
        _watch_tasks[channel.id] = watch_task
        return "ok"
    return "error: failed to start"
