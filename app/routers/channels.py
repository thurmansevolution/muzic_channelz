"""Channels API: list, m3u, yml for ErsatzTV, HDHomeRun-style playlist and guide."""
from __future__ import annotations

import asyncio
import base64
import re
import socket
from datetime import datetime, timedelta, timezone

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from app.config import settings
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

def _server_base_url() -> str:
    """Base URL for M3U/yml using this server's IP so the file works on any install.

    Uses MUZIC_PUBLIC_HOST if set (e.g. in Docker set to the host's LAN IP), otherwise
    _local_ip() so the downloadable file always points to the server it's running on.
    """
    import os
    from app.config import settings
    host = (os.environ.get("MUZIC_PUBLIC_HOST") or "").strip() or _local_ip()
    return f"http://{host}:{settings.port}"

router = APIRouter(prefix="/api/channels", tags=["channels"])


def _channel_logos_dir() -> Path:
    d = settings.data_dir / "channel_logos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stock_logo_path() -> Path | None:
    """Return path to default logo (tries frontend/public, then app/static for Docker)."""
    # __file__ is app/routers/channels.py -> parent.parent.parent is project root
    root = Path(__file__).resolve().parent.parent.parent
    for p in (root / "frontend" / "public" / "logo.png", root / "app" / "static" / "default-art.png"):
        if p.is_file():
            return p
    return None


def _channel_logo_bytes(channel_id: str) -> bytes | None:
    """Return PNG bytes for the channel logo (custom if uploaded, else stock), or None if no file."""
    logos_dir = _channel_logos_dir()
    custom = logos_dir / f"{channel_id}.png"
    if custom.is_file():
        try:
            return custom.read_bytes()
        except OSError:
            pass
    stock = _stock_logo_path()
    if stock:
        try:
            return stock.read_bytes()
        except OSError:
            pass
    return None


def _profile_name_for_channel(state, ffmpeg_profile_id: str) -> str:
    """Resolve FFmpeg profile id (or legacy name) to its display name."""
    if not ffmpeg_profile_id:
        return "default"
    profiles = state.ffmpeg_profiles or []
    for p in profiles:
        pid = (getattr(p, "id", None) or "").strip()
        pname = (p.name or "").strip()
        if pid and pid == (ffmpeg_profile_id or "").strip():
            return p.name or ffmpeg_profile_id
        if pname == (ffmpeg_profile_id or "").strip():
            return p.name or ffmpeg_profile_id
    if len(profiles) == 1:
        return profiles[0].name or ffmpeg_profile_id
    return ffmpeg_profile_id


def _station_name_for_channel(state, channel) -> str:
    """Resolve channel's Azuracast station to its display name (for default channel name)."""
    want = (getattr(channel, "azuracast_station_id", None) or "").strip()
    if not want:
        return ""
    for st in state.azuracast_stations or []:
        if (st.name or "").strip() == want or (st.station_shortcode or "").strip() == want:
            return (st.name or "").strip() or (st.station_shortcode or "").strip()
    return ""


@router.get("")
async def list_channels() -> list[dict]:
    state = await load_admin_state()
    out = []
    for c in state.channels:
        d = c.model_dump()
        d["is_running"] = services.is_running(c.id)
        d["ffmpeg_profile_name"] = _profile_name_for_channel(state, c.ffmpeg_profile_id or "")
        d["station_name"] = _station_name_for_channel(state, c)
        out.append(d)
    return out


@router.get("/playlist.m3u")
async def get_playlist_m3u():
    """Return a single M3U with all enabled channels for use in IPTV clients."""
    state = await load_admin_state()
    base = _server_base_url()
    channels = [c for c in (state.channels or []) if c.enabled]
    out_lines = ["#EXTM3U"]
    for i, c in enumerate(channels):
        ch_num = _guide_number(c, i)
        name = (c.name or _station_name_for_channel(state, c) or c.slug or c.id or "Channel").replace(",", " ")
        out_lines.append(f'#EXTINF:-1 tvg-chno="{ch_num}" tvg-name="{name}" group-title="muzic channelz",{name}')
        out_lines.append(f"{base}/stream/{c.id}/index.m3u8")
    body = "\n".join(out_lines) + "\n"
    return Response(
        content=body,
        media_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": 'attachment; filename="playlist.m3u"',
            "Cache-Control": "no-store, no-cache, must-revalidate",
        },
    )


def _guide_number(c, index: int) -> int:
    """Guide number for a channel (XMLTV/HDHomeRun). Uses guide_number if set, else 800+index (cable-style)."""
    n = getattr(c, "guide_number", None)
    if n is not None and n > 0:
        return n
    return 800 + index


@router.get("/guide.xml")
async def get_guide_xml(request: Request):
    """Return XMLTV guide for all enabled channels. Channel id matches HDHomeRun GuideNumber.
    Uses request base URL for icon URLs so Plex (and other clients) can fetch logos from the same origin as the guide."""
    state = await load_admin_state()
    base = str(request.base_url).rstrip("/")
    channels = [c for c in (state.channels or []) if c.enabled]
    now = datetime.now(timezone.utc)
    start_ts = now.strftime("%Y%m%d%H%M%S") + " +0000"
    end_dt = now + timedelta(hours=24)
    end_ts = end_dt.strftime("%Y%m%d%H%M%S") + " +0000"
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tv'
        ' source-info-name="muzic channelz"'
        ' source-info-url="' + base + '"'
        ' generator-info-name="muzic channelz"'
        ' generator-info-url="' + base + '">',
    ]
    for i, c in enumerate(channels):
        ch_num = _guide_number(c, i)
        ch_id = str(ch_num)
        name = (c.name or _station_name_for_channel(state, c) or c.slug or c.id or "Channel").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f'  <channel id="{ch_id}">')
        parts.append(f"    <display-name>{ch_num} {name}</display-name>")
        parts.append(f"    <display-name>{ch_num}</display-name>")
        parts.append(f"    <display-name>{name}</display-name>")
        # Use URL (same origin as guide) so Plex can fetch icons; data URI is not reliably supported.
        icon_src = f"{base}/api/channels/logo/{c.id}.png"
        parts.append(f'    <icon src="{icon_src}" width="120" height="120"/>')
        parts.append("  </channel>")
    for i, c in enumerate(channels):
        ch_num = _guide_number(c, i)
        ch_id = str(ch_num)
        name = (c.name or _station_name_for_channel(state, c) or c.slug or c.id or "Channel").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append("  <programme start=\"" + start_ts + "\" stop=\"" + end_ts + f"\" channel=\"{ch_id}\">")
        parts.append(f"    <title>{name}</title>")
        parts.append("    <desc>Live music channel</desc>")
        parts.append("  </programme>")
    parts.append("</tv>")
    body = "\n".join(parts)
    return Response(
        content=body.encode("utf-8"),
        media_type="application/xml; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/logo/{channel_id}")
async def get_channel_logo(channel_id: str):
    """Serve channel logo (e.g. for M3U clients). The XMLTV guide embeds logos as inline base64 so Plex displays them without HTTP/HTTPS or CORS issues. Accepts .../logo/id or .../logo/id.png."""
    if channel_id.endswith(".png"):
        channel_id = channel_id[:-4]
    state = await load_admin_state()
    if not next((c for c in (state.channels or []) if c.id == channel_id), None):
        raise HTTPException(404, "Channel not found")
    logos_dir = _channel_logos_dir()
    custom = logos_dir / f"{channel_id}.png"
    if custom.is_file():
        return FileResponse(custom, media_type="image/png")
    stock = _stock_logo_path()
    if stock:
        return FileResponse(stock, media_type="image/png")
    raise HTTPException(404, "No logo available")


@router.post("/logo/{channel_id}")
async def upload_channel_logo(channel_id: str, file: UploadFile = File(...)):
    """Upload a custom channel logo (used in XMLTV/guide). Replaces existing. PNG recommended."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    state = await load_admin_state()
    if not next((c for c in (state.channels or []) if c.id == channel_id), None):
        raise HTTPException(404, "Channel not found")
    logos_dir = _channel_logos_dir()
    path = logos_dir / f"{channel_id}.png"
    content = await file.read()
    path.write_bytes(content)
    return {"ok": True, "channel_id": channel_id}


@router.delete("/logo/{channel_id}")
async def remove_channel_logo(channel_id: str):
    """Remove the uploaded channel logo so the stock logo is used again."""
    state = await load_admin_state()
    if not next((c for c in (state.channels or []) if c.id == channel_id), None):
        raise HTTPException(404, "Channel not found")
    logos_dir = _channel_logos_dir()
    path = logos_dir / f"{channel_id}.png"
    if path.is_file():
        path.unlink()
    return {"ok": True, "channel_id": channel_id}


@router.get("/{channel_id}/m3u")
async def get_m3u(channel_id: str):
    """Return M3U playlist that points to the HLS stream. URL uses this server's IP (or MUZIC_PUBLIC_HOST in Docker)."""
    state = await load_admin_state()
    ch = next((c for c in state.channels if c.id == channel_id), None)
    if not ch:
        raise HTTPException(404, "Channel not found")
    from fastapi.responses import Response
    base = _server_base_url()
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
    """Return a YAML file for ErsatzTV Remote Stream. URL uses this server's IP (or MUZIC_PUBLIC_HOST in Docker)."""
    state = await load_admin_state()
    ch = next((c for c in state.channels if c.id == channel_id), None)
    if not ch:
        raise HTTPException(404, "Channel not found")
    base = _server_base_url()
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
            # Restart running channel so background/layout changes apply
            if services.is_running(channel_id) and "background_id" in body:
                asyncio.create_task(services.restart_channel(channel_id))
            result = state.channels[i].model_dump()
            result["is_running"] = services.is_running(channel_id)
            return result
    raise HTTPException(404, "Channel not found")
