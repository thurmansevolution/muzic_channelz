"""Channels API: list, m3u, yml for ErsatzTV."""
from __future__ import annotations

import asyncio
import re
import socket

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response
from app.store import load_admin_state, save_admin_state
from app.models import Channel
from app import services


def _local_ip() -> str:
    """Return this machine's local IP (for URLs reachable from other devices)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _slugify(name: str) -> str:
    """Turn channel name into a safe filename stem, e.g. 'Grunge Radio' -> 'grunge_radio'."""
    if not name or not name.strip():
        return "channel"
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_") or "channel"
    return s[:64]

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("")
async def list_channels() -> list[dict]:
    state = await load_admin_state()
    out = []
    for c in state.channels:
        d = c.model_dump()
        d["is_running"] = services.is_running(c.id)
        out.append(d)
    return out


@router.get("/{channel_id}/m3u")
async def get_m3u(channel_id: str):
    """Return M3U playlist that points to the HLS stream. Response is plain text with attachment so players get correct URL."""
    state = await load_admin_state()
    ch = next((c for c in state.channels if c.id == channel_id), None)
    if not ch:
        raise HTTPException(404, "Channel not found")
    from fastapi.responses import Response
    from app.config import settings
    base = f"http://localhost:{settings.port}"
    url = f"{base}/stream/{channel_id}/index.m3u8"
    body = f"#EXTM3U\n#EXTINF:-1,{ch.name}\n{url}\n"
    filename = f"{ch.slug or ch.id}.m3u".replace(" ", "_")
    return Response(
        content=body,
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{channel_id}/ersatztv-yml")
async def get_ersatztv_yml(channel_id: str) -> Response:
    """Return a YAML file for ErsatzTV Remote Stream. Filename is station name (e.g. grunge_radio.yml). URL uses this machine's IP."""
    state = await load_admin_state()
    ch = next((c for c in state.channels if c.id == channel_id), None)
    if not ch:
        raise HTTPException(404, "Channel not found")
    from app.config import settings
    host = _local_ip()
    base = f"http://{host}:{settings.port}"
    url = f"{base}/stream/{channel_id}/index.m3u8"
    yml = f"""# ErsatzTV Remote Stream — {ch.name or channel_id}
# Docs: https://ersatztv.org/docs/media/local/remotestreams/definition

url: "{url}"
is_live: true
duration: "24:00:00"
"""
    filename = f"{_slugify(ch.name or ch.slug or channel_id)}.yml"
    return Response(
        content=yml,
        media_type="text/yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{channel_id}/start")
async def start_channel(channel_id: str) -> dict:
    """Start a single channel."""
    result = await services.start_channel(channel_id)
    if result.startswith("error"):
        raise HTTPException(400, result)
    return {"status": "ok"}


@router.post("/{channel_id}/stop")
async def stop_channel(channel_id: str) -> dict:
    """Stop a single channel."""
    result = await services.stop_channel_api(channel_id)
    if result.startswith("error"):
        raise HTTPException(400, result)
    return {"status": "ok"}


@router.post("/{channel_id}/restart")
async def restart_channel(channel_id: str) -> dict:
    """Restart FFmpeg for a single channel."""
    result = await services.restart_channel(channel_id)
    if result.startswith("error"):
        raise HTTPException(400, result)
    return {"status": "ok"}


@router.patch("/{channel_id}")
async def update_channel(channel_id: str, body: dict) -> dict:
    """Update channel properties (e.g. background). Restart channel if running so changes apply."""
    state = await load_admin_state()
    for i, c in enumerate(state.channels):
        if c.id == channel_id:
            data = c.model_dump()
            data.update(body)
            state.channels[i] = Channel.model_validate(data)
            await save_admin_state(state)
            # If background changed and this channel is running, restart so changes apply
            if services.is_running(channel_id) and "background_id" in body:
                asyncio.create_task(services.restart_channel(channel_id))
            result = state.channels[i].model_dump()
            result["is_running"] = services.is_running(channel_id)
            return result
    raise HTTPException(404, "Channel not found")
