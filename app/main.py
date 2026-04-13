"""muzic channelz - FastAPI application."""
from contextlib import asynccontextmanager
from pathlib import Path
import time as _time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, channels, backgrounds, logs, system, hdhr, stream


def _clear_logs_on_startup() -> None:
    """Delete all log files so each container start has a clean log slate."""
    if not settings.logs_dir or not settings.logs_dir.exists():
        return
    for f in settings.logs_dir.iterdir():
        if f.is_file() and f.suffix in (".log", ".txt"):
            try:
                f.unlink()
            except OSError:
                pass


def _clear_stale_hls_segments() -> None:
    """Delete all HLS segments and playlists left over from a previous run."""
    streams_root = settings.data_dir / "streams"
    if not streams_root.exists():
        return
    for channel_dir in streams_root.iterdir():
        if not channel_dir.is_dir():
            continue
        for f in channel_dir.iterdir():
            if f.is_file() and f.suffix in (".m3u8", ".ts"):
                try:
                    f.unlink()
                except OSError:
                    pass


async def _idle_channel_checker() -> None:
    """Periodically stop channels that have been idle longer than channel_idle_shutdown_seconds."""
    import asyncio as _asyncio
    from app import services
    from app.store import load_admin_state
    from app.ffmpeg_runner import append_app_log
    from app.models import FFmpegSettings

    while True:
        await _asyncio.sleep(15)
        try:
            state = await load_admin_state()
            if not getattr(state, "service_started", False):
                continue
            fs = state.ffmpeg_settings or FFmpegSettings()
            idle_secs = getattr(fs, "channel_idle_shutdown_seconds", 300)
            if idle_secs <= 0:
                continue
            now = _time.time()
            for ch_id, session in list(services.get_sessions().items()):
                if not session.is_running:
                    continue
                last = session.last_activity
                idle_elapsed = int(now - last) if last > 0 else -1
                if last > 0 and (now - last) > idle_secs:
                    append_app_log(f"channel {ch_id} idle for >{idle_secs}s — auto-stopping", "warn")
                    await services.stop_channel(ch_id)
                elif last > 0:
                    append_app_log(f"idle check: channel {ch_id} active ({idle_elapsed}s since last activity, threshold {idle_secs}s)", "debug")
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.backgrounds_dir:
        settings.backgrounds_dir.mkdir(parents=True, exist_ok=True)
    if settings.logs_dir:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)

    _clear_logs_on_startup()
    _clear_stale_hls_segments()

    from app.store import load_admin_state, save_admin_state
    from app.models import FFmpegSettings
    import uuid as _uuid
    state = await load_admin_state()
    _dirty = False
    if not (state.hdhr_uuid or "").strip():
        state.hdhr_uuid = _uuid.uuid4().hex[:8].upper()
        _dirty = True
    if state.service_started:
        state.service_started = False
        _dirty = True
    if not state.ffmpeg_settings:
        state.ffmpeg_settings = FFmpegSettings()
        _dirty = True
    if getattr(state.ffmpeg_settings, "channel_idle_shutdown_seconds", 0) <= 60:
        state.ffmpeg_settings.channel_idle_shutdown_seconds = 300
        _dirty = True
    if getattr(state.ffmpeg_settings, "hls_time", 2) >= 2:
        state.ffmpeg_settings.hls_time = 1
        _dirty = True
    if getattr(state.ffmpeg_settings, "hls_list_size", 10) <= 10:
        state.ffmpeg_settings.hls_list_size = 15
        _dirty = True
    if _dirty:
        await save_admin_state(state)

    from app.ffmpeg_runner import append_app_log
    append_app_log("muzic channelz started — server is stopped. Use Administration to start the service.", "info")

    idle_task = _asyncio.create_task(_idle_channel_checker())

    yield

    idle_task.cancel()
    try:
        await idle_task
    except _asyncio.CancelledError:
        pass

    from app import services
    await services.stop_all_channels()


app = FastAPI(
    title="muzic channelz",
    description="Music channel streaming with overlay and Azuracast",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin.router)
app.include_router(channels.router)
app.include_router(backgrounds.router)
app.include_router(logs.router)
app.include_router(system.router)
app.include_router(stream.router)
# HDHomeRun / Live TV: root paths so they are not caught by SPA
app.get("/discover.json", include_in_schema=False)(hdhr.discover_json)
app.get("/device.json", include_in_schema=False)(hdhr.device_json)
app.get("/device.xml", include_in_schema=False)(hdhr.device_xml)
app.get("/lineup.json", include_in_schema=False)(hdhr.lineup_json)
app.get("/lineup.xml", include_in_schema=False)(hdhr.lineup_xml)
app.get("/guide.xml", include_in_schema=False)(hdhr.guide_xml)
app.get("/playlist.m3u", include_in_schema=False)(channels.get_playlist_m3u)
app.get("/lineup_status.json", include_in_schema=False)(hdhr.lineup_status_json)
app.include_router(hdhr.router)

_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

_streams_dir = settings.data_dir / "streams"
_streams_dir.mkdir(parents=True, exist_ok=True)

_HLS_MEDIA_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/MP2T",
}

_channel_starting: set[str] = set()


async def _start_channel_task(channel_id: str) -> None:
    from app import services
    try:
        await services.start_channel(channel_id)
    finally:
        _channel_starting.discard(channel_id)


@app.get("/stream/{path:path}")
async def serve_stream(path: str):
    """Serve HLS playlist and segments. Auto-starts the channel on first request if not running."""
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    from app import services
    import asyncio as _asyncio

    parts = path.split("/")
    channel_id = parts[0] if parts else None

    if channel_id:
        services.notify_stream_request(channel_id)

    from app.ffmpeg_runner import append_app_log
    _is_playlist = path.endswith("index.m3u8")

    if channel_id and not services.is_running(channel_id) and channel_id not in _channel_starting:
        from app.store import load_admin_state
        state = await load_admin_state()
        if state.service_started:
            ch = next((c for c in state.channels if c.id == channel_id), None)
        else:
            ch = None
        if ch and ch.enabled:
            _channel_starting.add(channel_id)
            append_app_log(f"channel {channel_id}: on-demand start triggered by stream request", "info")
            _asyncio.create_task(_start_channel_task(channel_id))
        elif not getattr(state, "service_started", False) and _is_playlist:
            append_app_log(f"serve_stream: channel {channel_id} playlist requested but service is stopped", "debug")
    elif channel_id and services.is_running(channel_id) and _is_playlist:
        append_app_log(f"serve_stream: channel {channel_id} HLS playlist request — already running", "debug")

    stream_file = _streams_dir / path
    # Wait when: (a) serve_stream itself started the channel, or (b) a session
    # exists (hdhr.py started it) but the file isn't ready yet.
    # Poll at 100ms so the conversion ffmpeg gets the m3u8 as soon as it appears.
    _session_exists = channel_id is not None and services.get_sessions().get(channel_id) is not None
    if channel_id in _channel_starting or (_session_exists and not stream_file.is_file()):
        if _is_playlist:
            append_app_log(f"serve_stream: waiting for channel {channel_id} to initialize", "debug")
        for _ in range(150):
            await _asyncio.sleep(0.1)
            stream_file = _streams_dir / path
            if stream_file.is_file() and channel_id not in _channel_starting:
                break
        if _is_playlist:
            append_app_log(f"serve_stream: channel {channel_id} wait complete — file_exists={stream_file.is_file()}", "debug")

    stream_file = _streams_dir / path
    if not stream_file.is_file() or not stream_file.resolve().is_relative_to(_streams_dir.resolve()):
        if _is_playlist:
            append_app_log(f"serve_stream: 404 for channel {channel_id} — file not found after wait", "debug")
        raise HTTPException(404, "Stream file not found. The channel may still be starting — try again in a moment.")
    media_type = _HLS_MEDIA_TYPES.get(stream_file.suffix.lower())
    return FileResponse(
        stream_file,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

def _default_logo_path():
    root = Path(__file__).resolve().parent.parent
    for p in (root / "frontend" / "public" / "logo.png", root / "app" / "static" / "default-art.png"):
        if p.is_file():
            return p
    return None
_logo_path = _default_logo_path()
if _logo_path is not None:
    @app.get("/logo.png")
    async def serve_logo():
        from fastapi.responses import FileResponse
        return FileResponse(_logo_path, media_type="image/png")

frontend_path = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_index_html = frontend_path / "index.html"
if _index_html.exists():
    _assets_dir = frontend_path / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        from fastapi.responses import FileResponse
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        if full_path.startswith("static/"):
            static_file = (_static_dir / full_path.replace("static/", "", 1)).resolve()
            if static_file.is_file() and static_file.is_relative_to(_static_dir.resolve()):
                return FileResponse(static_file)
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        if full_path and "." in full_path:
            f = (frontend_path / full_path).resolve()
            if f.is_file() and f.is_relative_to(frontend_path.resolve()):
                return FileResponse(f)
        return FileResponse(_index_html)
else:
    from fastapi.responses import RedirectResponse
    @app.get("/")
    async def root():
        return RedirectResponse(url="/docs")
