"""HDHomeRun protocol emulation for Live TV clients (e.g. Plex, Jellyfin)."""
from __future__ import annotations

import asyncio
import socket
import uuid as uuid_mod

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.store import load_admin_state


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _server_base_url(request: Request | None = None) -> str:
    """Base URL for responses; uses request host when available."""
    if request and request.url:
        base = str(request.base_url).rstrip("/")
        if base:
            return base
    import os
    host = (os.environ.get("MUZIC_PUBLIC_HOST") or "").strip() or _local_ip()
    return f"http://{host}:{settings.port}"


router = APIRouter(tags=["hdhr"])


def _discover_payload(state, base: str):
    device_id = (state.hdhr_uuid or "").strip()
    if not device_id:
        device_id = uuid_mod.uuid4().hex[:8].upper()
    tuner_count = max(1, min(32, state.hdhr_tuner_count or 4))
    return {
        "BaseURL": base,
        "DeviceAuth": "muzic",
        "DeviceID": device_id,
        "FirmwareName": "hdhomerun4_atsc",
        "FirmwareVersion": "20240101",
        "FriendlyName": "muzic channelz",
        "LineupURL": f"{base}/lineup.json",
        "ModelNumber": "HDHR4-2US",
        "TunerCount": tuner_count,
    }


async def discover_json(request: Request):
    """HDHomeRun discover endpoint for device discovery."""
    state = await load_admin_state()
    base = _server_base_url(request)
    return JSONResponse(_discover_payload(state, base))


async def device_json(request: Request):
    """Alias for discover.json used by some clients."""
    state = await load_admin_state()
    base = _server_base_url(request)
    return JSONResponse(_discover_payload(state, base))


async def lineup_json(request: Request):
    """HDHomeRun channel lineup. Each channel URL must return MPEG-TS when requested."""
    state = await load_admin_state()
    base = _server_base_url(request)
    channel_list = _lineup_channel_list(state, base)
    lineup = [{**ch, "DRM": 0, "Favorite": 0} for ch in channel_list]
    return JSONResponse(lineup)


async def lineup_status_json(request: Request):
    """HDHomeRun lineup status."""
    return JSONResponse({
        "ScanInProgress": 0,
        "ScanPossible": 1,
        "Source": "Antenna",
        "SourceList": ["Antenna"],
    })


def _lineup_channel_list(state, base: str):
    """Shared channel list for lineup.json and lineup.xml."""
    from app.routers.channels import _station_name_for_channel
    channels = [c for c in (state.channels or []) if c.enabled]
    out = []
    for i, c in enumerate(channels):
        gn = getattr(c, "guide_number", None)
        ch_num = (gn if gn is not None and gn > 0 else 800 + i)
        name = (c.name or _station_name_for_channel(state, c) or c.slug or c.id or "Channel").replace('"', "'")
        out.append({
            "GuideNumber": str(ch_num),
            "GuideName": name,
            "URL": f"{base}/hdhr/stream/{c.id}",
        })
    return out


async def lineup_xml(request: Request):
    """HDHomeRun lineup.xml: channel list in XML. EPG is served at /guide.xml."""
    state = await load_admin_state()
    base = _server_base_url(request)
    channels = _lineup_channel_list(state, base)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<Lineup>']
    for ch in channels:
        gn = ch["GuideNumber"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        name = ch["GuideName"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        url = ch["URL"].replace("&", "&amp;")
        parts.append(f'  <Program GuideNumber="{gn}" GuideName="{name}" URL="{url}"/>')
    parts.append("</Lineup>")
    from fastapi.responses import Response
    return Response(
        content="\n".join(parts).encode("utf-8"),
        media_type="application/xml; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


async def guide_xml(request: Request):
    """XMLTV guide at device root. Pass request so icon URLs use same host as guide."""
    from app.routers.channels import get_guide_xml
    return await get_guide_xml(request)


@router.get("/hdhr/stream/{channel_id}")
async def stream_channel_ts(channel_id: str):
    """Stream channel as MPEG-TS for HDHomeRun clients. Converts HLS to TS on the fly."""
    state = await load_admin_state()
    ch = next((c for c in (state.channels or []) if c.id == channel_id and c.enabled), None)
    if not ch:
        raise HTTPException(404, "Channel not found")
    hls_url = f"http://127.0.0.1:{settings.port}/stream/{channel_id}/index.m3u8"

    async def generate():
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-i", hls_url,
            "-c", "copy",
            "-f", "mpegts",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            while proc.stdout:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        except asyncio.CancelledError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    return StreamingResponse(
        generate(),
        media_type="video/mp2t",
        headers={"Cache-Control": "no-store", "Connection": "close"},
    )
