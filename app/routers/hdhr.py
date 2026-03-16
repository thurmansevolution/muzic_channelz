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
    """Stream channel as MPEG-TS for HDHomeRun clients (Plex, Kodi, etc.).

    ErsatzTV-style: one lightweight ffmpeg per client reads the HLS playlist
    via HTTP and pipes MPEG-TS directly to the HTTP response.
    The m3u8 wait and ffmpeg start happen BEFORE the StreamingResponse is
    returned so Plex never gets a 200 with no bytes flowing.
    """
    from app import services
    from app.ffmpeg_runner import append_app_log
    from app.models import FFmpegSettings

    state = await load_admin_state()
    ch = next((c for c in (state.channels or []) if c.id == channel_id and c.enabled), None)
    if not ch:
        raise HTTPException(404, "Channel not found")

    if getattr(state, "service_started", False):
        await services.start_channel(channel_id)

    services.notify_stream_request(channel_id)

    ff_settings = state.ffmpeg_settings or FFmpegSettings()
    ffmpeg_executable = (ff_settings.ffmpeg_path or "ffmpeg").strip() or "ffmpeg"

    streams_dir = settings.data_dir / "streams" / channel_id
    m3u8_path = streams_dir / "index.m3u8"

    # Wait for the HLS playlist to appear BEFORE returning the response.
    # This gives Plex a proper 503 if the channel never starts, instead of
    # a 200 with no data (which Plex treats as a stream error).
    for _ in range(40):
        if m3u8_path.is_file():
            break
        services.notify_stream_request(channel_id)
        await asyncio.sleep(0.5)

    if not m3u8_path.is_file():
        append_app_log(f"hdhr/{channel_id}: m3u8 never appeared — returning 503", "warn")
        raise HTTPException(503, "Channel not ready — try again shortly")

    # Use the HTTP URL so ffmpeg's HLS demuxer live-polls for new segments.
    # A local file:// path causes ffmpeg to read the playlist once and exit (VOD behaviour).
    hls_url = f"http://127.0.0.1:{settings.port}/stream/{channel_id}/index.m3u8"

    logs_dir = settings.data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"ffmpeg_hdhr_{channel_id}.log"

    # Start conversion ffmpeg NOW (before the generator) so data is flowing
    # before the first yield — eliminating the first-byte delay Plex times out on.
    # -live_start_index -1      → start from the most recent segment.
    # -reconnect* flags         → survive brief HLS gaps (e.g. main ffmpeg auto-restart).
    # -timeout 30000000         → 30s HTTP timeout in microseconds.
    # -c copy                   → no re-encoding, just container remux.
    # -mpegts_flags +resend_headers → re-send PAT/PMT tables periodically (Plex needs this).
    # -f mpegts pipe:1          → continuous MPEG-TS to stdout.
    stderr_f = open(log_path, "ab")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_executable,
        "-hide_banner",
        "-loglevel", "warning",
        "-reconnect", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
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
    append_app_log(f"hdhr/{channel_id}: ErsatzTV-style TS stream started (pid={proc.pid})", "debug")

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
