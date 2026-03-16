"""Stream API: ensure channel is running before loading HLS (so backend is hit and FFmpeg starts)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import services
from app.ffmpeg_runner import append_app_log

router = APIRouter(prefix="/api/stream", tags=["stream"])


@router.get("/ensure/{channel_id}")
async def ensure_stream(channel_id: str) -> dict:
    """
    Ensure the server is enabled and this channel's FFmpeg is running.
    Call this when opening the live feed so the backend is hit (same as other API calls)
    and the channel starts before the HLS URL is loaded.
    """
    if not channel_id or not channel_id.strip():
        raise HTTPException(400, "channel_id required")
    channel_id = channel_id.strip()
    append_app_log(f"stream ensure request channel_id={channel_id!r}", "debug")
    ok = await services.ensure_channel_running(channel_id)
    if ok:
        services.notify_stream_request(channel_id)
    append_app_log(f"stream ensure channel_id={channel_id!r} => ok={ok}", "debug")
    return {
        "ok": ok,
        "channel_id": channel_id,
        "message": "Channel started. Load the stream URL." if ok else "Server disabled or channel not available. Start the server in Administration.",
    }
