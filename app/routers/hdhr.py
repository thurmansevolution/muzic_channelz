"""HDHomeRun protocol emulation for Live TV clients (e.g. Plex, Jellyfin)."""
from __future__ import annotations

import asyncio
import socket
import time
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
            "ImageURL": f"{base}/api/channels/logo/{c.id}",
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
async def stream_channel_ts(channel_id: str, request: Request):
    """Stream channel as MPEG-TS for HDHomeRun clients. Converts HLS to TS on the fly."""
    from app import services
    state = await load_admin_state()
    ch = next((c for c in (state.channels or []) if c.id == channel_id and c.enabled), None)
    if not ch:
        raise HTTPException(404, "Channel not found")

    if getattr(state, "service_started", False):
        await services.start_channel(channel_id)

    hls_file = settings.data_dir / "streams" / channel_id / "index.m3u8"
    if not hls_file.is_file():
        for _ in range(20):
            await asyncio.sleep(1)
            if hls_file.is_file():
                break
    if not hls_file.is_file():
        raise HTTPException(503, "Channel not ready — try again shortly")

    hls_url = f"http://127.0.0.1:{settings.port}/stream/{channel_id}/index.m3u8"
    log_path = settings.data_dir / "logs" / f"ffmpeg_hdhr_{channel_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    from app import services
    from app.ffmpeg_runner import append_app_log

    async def generate():
        services.notify_stream_request(channel_id)
        stderr_f = open(log_path, "ab")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-loglevel", "warning",
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-i", hls_url,
            "-c", "copy",
            "-f", "mpegts",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_f,
        )
        append_app_log(f"hdhr/{channel_id}: conversion ffmpeg started (pid={proc.pid})", "debug")
        try:
            while proc.stdout:
                services.notify_stream_request(channel_id)
                read_task = asyncio.create_task(proc.stdout.read(65536))
                disconnect_task = asyncio.create_task(request.is_disconnected())
                done, pending = await asyncio.wait(
                    [read_task, disconnect_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
                if disconnect_task in done:
                    try:
                        if disconnect_task.result():
                            append_app_log(f"hdhr/{channel_id}: client disconnected", "debug")
                            break
                    except Exception:
                        break
                if read_task in done:
                    try:
                        chunk = read_task.result()
                    except Exception:
                        break
                    if not chunk:
                        break
                    yield chunk
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            stderr_f.close()
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except Exception:
                pass
            append_app_log(f"hdhr/{channel_id}: conversion ffmpeg ended (returncode={proc.returncode})", "debug")

    return StreamingResponse(
        generate(),
        media_type="video/mp2t",
        headers={"Cache-Control": "no-store", "Connection": "close"},
    )
