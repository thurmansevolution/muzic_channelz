"""services.py — thin channel manager.

All per-channel state and ffmpeg lifecycle logic lives in ChannelSession
(app/channel_session.py).  This module is a thin coordinator that:
  - Keeps a dict of active ChannelSession objects
  - Exposes start/stop/status helpers used by routers and main.py
  - Tracks which channels were explicitly stopped by the user
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from app.ffmpeg_runner import append_app_log
from app.store import load_admin_state
from app.channel_session import ChannelSession

_log = logging.getLogger("app.services")

_sessions: dict[str, ChannelSession] = {}
_user_stopped: set[str] = set()
_starting: set[str] = set()

_hdhr_procs: dict[str, set] = {}


def register_hdhr_proc(channel_id: str, proc) -> None:
    """Register a conversion ffmpeg proc so it can be killed when the channel stops."""
    _hdhr_procs.setdefault(channel_id, set()).add(proc)


def unregister_hdhr_proc(channel_id: str, proc) -> None:
    """Remove a conversion ffmpeg proc from the registry (called on clean exit)."""
    procs = _hdhr_procs.get(channel_id)
    if procs:
        procs.discard(proc)


def _kill_hdhr_procs(channel_id: str) -> None:
    """Terminate all active conversion ffmpeg procs for a channel."""
    procs = _hdhr_procs.pop(channel_id, set())
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    if procs:
        append_app_log(f"channel {channel_id}: killed {len(procs)} conversion ffmpeg(s)", "debug")


# ------------------------------------------------------------------ #
# Bulk start / stop (service-level)                                   #
# ------------------------------------------------------------------ #

async def start_all_channels() -> dict[str, str]:
    """Start all enabled channels. Returns {channel_id: 'ok'|'error:...'}."""
    state = await load_admin_state()
    results: dict[str, str] = {}
    for ch in state.channels:
        if ch.enabled:
            results[ch.id] = await start_channel(ch.id)
    return results


async def stop_all_channels() -> None:
    """Stop all running channel sessions."""
    ids = list(_sessions.keys())
    if ids:
        append_app_log(f"stopping all channels: {ids}", "debug")
    for cid in ids:
        _kill_hdhr_procs(cid)
        session = _sessions.pop(cid, None)
        if session:
            await session.stop()
    _starting.clear()


# ------------------------------------------------------------------ #
# Per-channel start / stop                                            #
# ------------------------------------------------------------------ #

async def start_channel(channel_id: str) -> str:
    """Start a channel session if not already running."""
    if channel_id in _user_stopped:
        append_app_log(f"channel {channel_id}: cleared from user-stopped set (explicit start)", "debug")
    _user_stopped.discard(channel_id)

    existing = _sessions.get(channel_id)
    if existing and existing.is_running:
        return "ok"
    if channel_id in _starting:
        return "ok"

    _starting.add(channel_id)
    try:
        state = await load_admin_state()
        ch = next((c for c in state.channels if c.id == channel_id), None)
        if not ch:
            return "error: channel not found"
        if not ch.enabled:
            return "error: channel disabled"

        if existing:
            await existing.stop()

        session = ChannelSession(channel_id)
        _sessions[channel_id] = session
        session.start()
        return "ok"
    except Exception as e:
        append_app_log(f"channel {channel_id} start error: {e}", "error")
        return f"error: {e}"
    finally:
        _starting.discard(channel_id)


async def stop_channel(channel_id: str) -> None:
    """Stop a channel session and remove it."""
    _kill_hdhr_procs(channel_id)
    session = _sessions.pop(channel_id, None)
    if session:
        await session.stop()


async def stop_channel_api(channel_id: str, grace: bool = False) -> str:
    """Stop a channel (API / WebUI endpoint).

    grace=True means the client navigated away — don't mark as user-stopped.
    Returns 'ok'.
    """
    if not is_running(channel_id):
        append_app_log(f"channel {channel_id}: stop_channel_api called but not running", "debug")
        return "ok"
    if not grace:
        _user_stopped.add(channel_id)
        append_app_log(f"channel {channel_id}: added to user-stopped set", "debug")
    await stop_channel(channel_id)
    return "ok"


async def restart_channel(channel_id: str) -> str:
    """Restart a channel (full clean restart, not auto-restart)."""
    await stop_channel(channel_id)
    state = await load_admin_state()
    ch = next((c for c in state.channels if c.id == channel_id), None)
    if not ch:
        return "error: channel not found"
    if not ch.enabled:
        return "error: channel disabled"
    return await start_channel(channel_id)


# ------------------------------------------------------------------ #
# Status helpers                                                      #
# ------------------------------------------------------------------ #

def is_running(channel_id: str) -> bool:
    session = _sessions.get(channel_id)
    return session is not None and session.is_running


def notify_stream_request(channel_id: str) -> None:
    """Reset the idle timer for a channel (called on every stream/segment request)."""
    session = _sessions.get(channel_id)
    if session:
        session.notify_activity()


async def ensure_channel_running(channel_id: str) -> bool:
    """Start the channel if not running and the service is enabled. Returns True if running."""
    state = await load_admin_state()
    if not getattr(state, "service_started", False):
        return False
    ch = next((c for c in (state.channels or []) if c.id == channel_id), None)
    if not ch or not ch.enabled:
        return False
    if is_running(channel_id):
        return True
    result = await start_channel(channel_id)
    return result == "ok"


def get_sessions() -> dict[str, ChannelSession]:
    """Return the active session dict (read-only use only)."""
    return _sessions


# ------------------------------------------------------------------ #
# Live log subscription                                               #
# ------------------------------------------------------------------ #

def subscribe_logs(channel_id: str, callback: Callable[[str], None]) -> Callable[[], None]:
    """Subscribe to live ffmpeg log lines for a channel. Returns unsubscribe fn."""
    session = _sessions.get(channel_id)
    if session:
        session.log_listeners.append(callback)

    def unsub() -> None:
        s = _sessions.get(channel_id)
        if s and callback in s.log_listeners:
            s.log_listeners.remove(callback)

    return unsub
