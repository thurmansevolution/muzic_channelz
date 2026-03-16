"""Live logs API: tail FFmpeg log by channel, or application log."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from app.ffmpeg_runner import get_channel_log_path, get_app_log_path, filter_log_lines

router = APIRouter(prefix="/api/logs", tags=["logs"])


async def _get_log_level() -> str:
    try:
        from app.store import load_admin_state
        state = await load_admin_state()
        return (getattr(state.ffmpeg_settings, "log_level", None) or "debug").lower()
    except Exception:
        return "debug"


@router.get("/app", response_class=PlainTextResponse)
async def get_app_log(tail: int = 500) -> str:
    """Return the last N lines of the application log, filtered by configured log level."""
    path = get_app_log_path()
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    level = await _get_log_level()
    filtered = filter_log_lines(lines, level, is_app_log=True)
    return "\n".join(filtered[-tail:]) if tail else "\n".join(filtered)


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
    """Return the last N lines of a channel's FFmpeg log, filtered by configured log level."""
    path = get_channel_log_path(channel_id)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    level = await _get_log_level()
    filtered = filter_log_lines(lines, level, is_app_log=False)
    return "\n".join(filtered[-tail:]) if tail else "\n".join(filtered)
