"""muzic channelz - FastAPI application."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, channels, backgrounds, logs, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.backgrounds_dir:
        settings.backgrounds_dir.mkdir(parents=True, exist_ok=True)
    if settings.logs_dir:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
    yield
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

_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

_streams_dir = settings.data_dir / "streams"
_streams_dir.mkdir(parents=True, exist_ok=True)

_HLS_MEDIA_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/MP2T",
}

@app.get("/stream/{path:path}")
async def serve_stream(path: str):
    """Serve HLS playlist and segments with correct MIME types."""
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    stream_file = _streams_dir / path
    if not stream_file.is_file() or not stream_file.resolve().is_relative_to(_streams_dir.resolve()):
        raise HTTPException(404, "Stream file not found. Start the service and ensure the channel is running.")
    media_type = _HLS_MEDIA_TYPES.get(stream_file.suffix.lower())
    return FileResponse(
        stream_file,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

_logo_path = Path(__file__).resolve().parent.parent / "frontend" / "public" / "logo.png"
if _logo_path.exists():
    @app.get("/logo.png")
    async def serve_logo():
        from fastapi.responses import FileResponse
        return FileResponse(_logo_path, media_type="image/png")

frontend_path = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_path.exists():
    app.mount("/assets", StaticFiles(directory=frontend_path / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        from fastapi.responses import FileResponse
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        if full_path.startswith("static/"):
            static_file = _static_dir / full_path.replace("static/", "", 1)
            if static_file.is_file():
                return FileResponse(static_file)
            from fastapi import HTTPException
            raise HTTPException(404, "Not found")
        if full_path and "." in full_path:
            f = frontend_path / full_path
            if f.exists():
                return FileResponse(f)
        return FileResponse(frontend_path / "index.html")
else:
    from fastapi.responses import RedirectResponse
    @app.get("/")
    async def root():
        return RedirectResponse(url="/docs")
