"""Live logs API: tail FFmpeg log by channel, or application log."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from app.ffmpeg_runner import get_channel_log_path, get_app_log_path

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/app", response_class=PlainTextResponse)
async def get_app_log(tail: int = 500) -> str:
    """Return the last N lines of the application log (troubleshooting, excluding FFmpeg)."""
    path = get_app_log_path()
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return "\n".join(lines[-tail:]) if tail else "\n".join(lines)


@router.delete("/app")
async def clear_app_log() -> dict:
    """Truncate the application log (for starting a clean test)."""
    path = get_app_log_path()
    if path.exists():
        try:
            path.write_text("", encoding="utf-8")
        except OSError as e:
            from fastapi import HTTPException
            raise HTTPException(500, f"Could not clear log: {e}") from e
    return {"ok": True}


@router.get("/{channel_id}", response_class=PlainTextResponse)
async def get_log_content(channel_id: str, tail: int = 200) -> str:
    """Return the last N lines of a channel's FFmpeg log."""
    path = get_channel_log_path(channel_id)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return "\n".join(lines[-tail:]) if tail else "\n".join(lines)
