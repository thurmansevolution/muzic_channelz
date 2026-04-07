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
        "Source": "Cable",
        "SourceList": ["Cable"],
    })


async def device_xml(request: Request):
    """UPnP/DLNA device description. Plex polls this URL to verify the tuner is online.
    Without it, Plex marks the device as 'Device not found' in Live TV & DVR settings."""
    from fastapi.responses import Response as _Response
    state = await load_admin_state()
    device_id = (state.hdhr_uuid or "").strip()
    if not device_id:
        device_id = str(uuid_mod.uuid4())
    base = _server_base_url(request)
    xml = f"""<root xmlns="urn:schemas-upnp-org:device-1-0">
    <URLBase>{base}</URLBase>
    <specVersion>
        <major>1</major>
        <minor>0</minor>
    </specVersion>
    <device>
        <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
        <friendlyName>muzic channelz</friendlyName>
        <manufacturer>Silicondust</manufacturer>
        <modelName>HDTC-2US</modelName>
        <modelNumber>HDTC-2US</modelNumber>
        <serialNumber>{device_id}</serialNumber>
        <UDN>uuid:{device_id}</UDN>
    </device>
</root>"""
    return _Response(
        content=xml.encode("utf-8"),
        media_type="application/xml; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


def _lineup_channel_list(state, base: str):
    """Shared channel list for lineup.json and lineup.xml."""
    from app.routers.channels import _station_name_for_channel, _logo_version
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
            "ImageURL": f"{base}/api/channels/logo/{c.id}?v={_logo_version(c.id)}",
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
    """Stream channel as MPEG-TS for HDHomeRun clients (Plex, Kodi, etc.).

    ErsatzTV-style: return HTTP 200 to Plex immediately, then let the
    conversion ffmpeg handle waiting for HLS segments via serve_stream's
    session-aware wait loop.  This eliminates the Python-level polling
    delay and gets data flowing to Plex as fast as possible.
    """
    if not all(c.isalnum() or c in "-_" for c in channel_id):
        raise HTTPException(400, "Invalid channel ID")
    from app import services
    from app.ffmpeg_runner import append_app_log
    from app.models import FFmpegSettings

    state = await load_admin_state()
    ch = next((c for c in (state.channels or []) if c.id == channel_id and c.enabled), None)
    if not ch:
        raise HTTPException(404, "Channel not found")

    if not getattr(state, "service_started", False):
        raise HTTPException(503, "Service not started — enable the service in Administration first")

    await services.start_channel(channel_id)
    services.notify_stream_request(channel_id)

    ff_settings = state.ffmpeg_settings or FFmpegSettings()
    ffmpeg_executable = (ff_settings.ffmpeg_path or "ffmpeg").strip() or "ffmpeg"

    # Use the HTTP URL so ffmpeg's HLS demuxer live-polls for new segments.
    # serve_stream has a session-aware wait loop: if the channel session exists
    # but the m3u8 isn't ready yet it blocks (async) at 100ms intervals for up
    # to 15s before returning 404 — so the conversion ffmpeg never gets a 404
    # during a normal cold start.
    hls_url = f"http://127.0.0.1:{settings.port}/stream/{channel_id}/index.m3u8"

    logs_dir = settings.data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"ffmpeg_hdhr_{channel_id}.log"

    # Spawn conversion ffmpeg IMMEDIATELY — do not wait for m3u8 to exist.
    # HTTP 200 is returned to Plex as soon as the StreamingResponse is created,
    # so Plex sees an instant response and simply waits for data to flow.
    #
    # -probesize 500000         → 500KB probe (default 5MB) — saves ~3-4s
    # -analyzeduration 500000   → 0.5s analyze (default 5s)  — saves ~3-4s
    # -fflags +nobuffer         → disable output buffering — first byte ASAP
    # -max_delay 0              → zero demuxer delay
    # -live_start_index -1      → start from the most recent HLS segment
    # -reconnect* flags         → survive brief HLS gaps (main ffmpeg restart)
    # -reconnect_delay_max 2    → retry within 2s (not 5s) on HLS gap
    # -timeout 30000000         → 30s HTTP timeout in microseconds
    # -c copy                   → no re-encoding, just container remux
    # -mpegts_flags +resend_headers → re-send PAT/PMT periodically (Plex needs this)
    # -f mpegts pipe:1          → continuous MPEG-TS to stdout
    stderr_f = open(log_path, "ab")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel", "warning",
        "-probesize", "500000",
        "-analyzeduration", "500000",
        "-fflags", "+nobuffer",
        "-max_delay", "0",
        "-reconnect", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "2",
        "-timeout", "30000000",
        "-live_start_index", "-1",
        "-i", hls_url,
        "-c", "copy",
        "-mpegts_flags", "+resend_headers",
        "-f", "mpegts",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=stderr_f,
    )
    append_app_log(f"hdhr/{channel_id}: conversion ffmpeg started immediately (pid={proc.pid})", "debug")

    async def generate():
        disconnect_check = asyncio.create_task(request.is_disconnected())
        try:
            while True:
                # Non-blocking disconnect check.
                if disconnect_check.done():
                    try:
                        if disconnect_check.result():
                            append_app_log(f"hdhr/{channel_id}: client disconnected", "debug")
                            break
                    except Exception:
                        break
                    disconnect_check = asyncio.create_task(request.is_disconnected())

                services.notify_stream_request(channel_id)

                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=30.0)
                except asyncio.TimeoutError:
                    if proc.returncode is not None:
                        append_app_log(f"hdhr/{channel_id}: conversion ffmpeg exited (code={proc.returncode})", "debug")
                        break
                    append_app_log(f"hdhr/{channel_id}: no data for 30s — closing stream", "warn")
                    break

                if not chunk:
                    append_app_log(f"hdhr/{channel_id}: conversion ffmpeg stdout EOF (code={proc.returncode})", "debug")
                    break

                yield chunk

        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            disconnect_check.cancel()
            try:
                await disconnect_check
            except Exception:
                pass
            if proc.returncode is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            try:
                stderr_f.close()
            except Exception:
                pass
            append_app_log(f"hdhr/{channel_id}: TS stream ended", "debug")

    return StreamingResponse(
        generate(),
        media_type="video/mp2t",
        headers={"Cache-Control": "no-store", "Connection": "close"},
    )
