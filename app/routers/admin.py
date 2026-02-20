"""Administration API: state, start/stop service, backup/restore."""
from __future__ import annotations

import base64
import json
import logging
import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.ffmpeg_runner import get_channel_log_path
from app.models import AdminState, BackgroundTemplate
from app.store import load_admin_state, save_admin_state, load_backgrounds, save_backgrounds
from app import services

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/state", response_model=AdminState)
async def get_state() -> AdminState:
    """Return admin state with service_started and channel running state reflecting actual process state."""
    state = await load_admin_state()
    state.service_started = any(services.is_running(c.id) for c in state.channels)
    # Return updated HLS defaults for older saved configs so UI shows current defaults
    if state.ffmpeg_settings and state.ffmpeg_settings.hls_time == 4 and state.ffmpeg_settings.hls_list_size == 6:
        state = state.model_copy(update={
            "ffmpeg_settings": state.ffmpeg_settings.model_copy(update={"hls_time": 2, "hls_list_size": 4}),
        })
    return state


def _ensure_unique_channel_ids(state: AdminState) -> AdminState:
    """Ensure every channel has a unique id so streams and now-playing don't collide."""
    import uuid
    seen: set[str] = set()
    channels = list(state.channels)
    for i, ch in enumerate(channels):
        cid = (ch.id or "").strip()
        if not cid or cid in seen:
            new_id = str(uuid.uuid4())[:8]
            while new_id in seen:
                new_id = str(uuid.uuid4())[:8]
            seen.add(new_id)
            channels[i] = ch.model_copy(update={"id": new_id})
        else:
            seen.add(cid)
    return state.model_copy(update={"channels": channels})


@router.put("/state", response_model=AdminState)
async def put_state(state: AdminState) -> AdminState:
    state = _ensure_unique_channel_ids(state)
    old_state = await load_admin_state()
    old_ids = {c.id for c in old_state.channels if c.id}
    new_ids = {c.id for c in state.channels if c.id}
    removed_ids = old_ids - new_ids
    for channel_id in removed_ids:
        await services.stop_channel(channel_id)
        stream_dir = settings.data_dir / "streams" / channel_id
        if stream_dir.exists():
            try:
                shutil.rmtree(stream_dir)
            except OSError:
                pass
        log_path = get_channel_log_path(channel_id)
        if log_path.exists():
            try:
                log_path.unlink()
            except OSError:
                pass
    await save_admin_state(state)
    return state


@router.post("/start-service")
async def start_service() -> dict:
    """Start all music channels."""
    import traceback
    from app.ffmpeg_runner import append_app_log
    log = logging.getLogger("app.routers.admin")
    try:
        state = await load_admin_state()
        enabled = [c for c in state.channels if c.enabled]
        if not enabled:
            return {
                "ok": False,
                "channels": {},
                "message": "No enabled channels. Add a channel, assign a station and FFmpeg profile, enable it, Save, then Start service.",
            }
        results = await services.start_all_channels()
        state = await load_admin_state()
        state.service_started = any(services.is_running(c.id) for c in state.channels)
        await save_admin_state(state)
        started = sum(1 for v in results.values() if v == "ok")
        failed = [cid for cid, v in results.items() if v != "ok"]
        if started:
            append_app_log(f"service started ({started} channel(s))")
        if failed:
            append_app_log(f"channel(s) failed to start: {', '.join(f'{c}: {results[c]}' for c in failed)}")
        return {
            "ok": bool(started),
            "channels": results,
            "message": f"Started {started} of {len(enabled)} channel(s)." if started else (
                "No channel could be started. Check Live logs for FFmpeg errors and that each channel has a station and FFmpeg profile."
            ),
        }
    except Exception as e:
        log.exception("start-service failed")
        append_app_log(f"start-service error: {e!s}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop-service")
async def stop_service() -> dict:
    """Stop all channel processes."""
    from app.ffmpeg_runner import append_app_log
    await services.stop_all_channels()
    state = await load_admin_state()
    state.service_started = False
    await save_admin_state(state)
    append_app_log("service stopped (all channels)")
    return {"ok": True}


def _channel_logos_dir():
    d = settings.data_dir / "channel_logos"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/backup")
async def export_backup(include_images: bool = True) -> JSONResponse:
    """Export full config backup: admin state, backgrounds (+ images), and custom channel logos."""
    state = await load_admin_state()
    backgrounds = await load_backgrounds()
    payload = {
        "version": 2,
        "admin_state": state.model_dump(),
        "backgrounds": [b.model_dump() for b in backgrounds],
        "background_images": {},
        "channel_logos": {},
    }
    if include_images and settings.backgrounds_dir:
        root = settings.backgrounds_dir
        for b in backgrounds:
            if b.is_stock or not b.image_path:
                continue
            path = root / b.image_path
            if path.exists():
                try:
                    payload["background_images"][b.id] = base64.b64encode(path.read_bytes()).decode("ascii")
                except OSError:
                    pass
    logos_dir = _channel_logos_dir()
    for c in state.channels or []:
        if not c.id:
            continue
        path = logos_dir / f"{c.id}.png"
        if path.exists():
            try:
                payload["channel_logos"][c.id] = base64.b64encode(path.read_bytes()).decode("ascii")
            except OSError:
                pass
    return JSONResponse(content=payload)


class RestoreBody(BaseModel):
    """Request body for POST /api/admin/restore."""

    admin_state: dict
    backgrounds: list[dict]
    background_images: dict[str, str] = {}
    channel_logos: dict[str, str] = {}


@router.post("/restore")
async def restore_backup(body: RestoreBody) -> dict:
    """Restore full config from a backup. Stops the service, writes state and backgrounds (and images if provided)."""
    await services.stop_all_channels()

    state_restored = AdminState.model_validate(body.admin_state)
    state_restored.service_started = False
    await save_admin_state(state_restored)

    root = settings.backgrounds_dir or settings.data_dir / "backgrounds"
    root.mkdir(parents=True, exist_ok=True)
    for bid, b64 in (body.background_images or {}).items():
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception:
            continue
        bg = next((b for b in body.backgrounds if b.get("id") == bid), None)
        if not bg or bg.get("is_stock") or not bg.get("image_path"):
            continue
        path = root / bg["image_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    templates = [BackgroundTemplate.model_validate(b) for b in (body.backgrounds or [])]
    await save_backgrounds(templates)

    logos_dir = _channel_logos_dir()
    for channel_id, b64 in (body.channel_logos or {}).items():
        if not channel_id or not isinstance(b64, str):
            continue
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception:
            continue
        path = logos_dir / f"{channel_id}.png"
        try:
            path.write_bytes(raw)
        except OSError:
            pass

    return {"ok": True, "message": "Configuration restored. Start the service to apply."}


@router.delete("/metadata-cache")
async def clear_metadata_cache() -> dict:
    """Clear the local metadata cache (artist bios and images). Next play of each artist will fetch from providers again."""
    from app.metadata_cache import clear_cache
    success, message = clear_cache()
    return {"ok": success, "message": message}
