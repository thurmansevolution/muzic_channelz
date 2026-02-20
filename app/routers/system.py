"""System API: resource usage for Home dashboard and public URL for M3U/XMLTV."""
from __future__ import annotations

import os
import socket

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api/system", tags=["system"])


def _local_ip() -> str:
    """Return this machine's LAN IP (for URLs usable from other devices)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@router.get("/public-url")
async def get_public_url() -> dict:
    """Return the base URL to use for M3U/XMLTV so it works from other devices (uses LAN IP or MUZIC_PUBLIC_HOST)."""
    host = (os.environ.get("MUZIC_PUBLIC_HOST") or "").strip() or _local_ip()
    base_url = f"http://{host}:{settings.port}"
    return {"base_url": base_url}


def _app_process_stats(psutil_mod):
    """Return combined CPU % and RSS for this process and all its children (muzic channelz)."""
    try:
        import time
        proc = psutil_mod.Process()
        children = proc.children(recursive=True)
        all_procs = [proc] + children
        total_rss = sum(p.memory_info().rss for p in all_procs)
        for p in all_procs:
            p.cpu_percent()
        time.sleep(0.15)
        app_cpu = sum(p.cpu_percent() or 0 for p in all_procs)
        return {"app_cpu_percent": round(app_cpu, 1), "app_memory_bytes": total_rss}
    except Exception:
        return {"app_cpu_percent": None, "app_memory_bytes": 0}


@router.get("/stats")
async def get_system_stats() -> dict:
    """Return CPU and memory usage (current vs total) for the host running the app."""
    try:
        import psutil
    except ImportError:
        return {
            "cpu_percent": None,
            "cpu_count": 0,
            "memory_used_bytes": 0,
            "memory_total_bytes": 0,
            "memory_percent": None,
            "app_cpu_percent": None,
            "app_memory_bytes": 0,
            "error": "psutil not installed",
        }
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count() or 0
        mem = psutil.virtual_memory()
        app_stats = _app_process_stats(psutil)
        return {
            "cpu_percent": round(cpu_percent, 1),
            "cpu_count": cpu_count,
            "memory_used_bytes": mem.used,
            "memory_total_bytes": mem.total,
            "memory_percent": round(mem.percent, 1),
            "app_cpu_percent": app_stats["app_cpu_percent"],
            "app_memory_bytes": app_stats["app_memory_bytes"],
        }
    except Exception as e:
        return {
            "cpu_percent": None,
            "cpu_count": 0,
            "memory_used_bytes": 0,
            "memory_total_bytes": 0,
            "memory_percent": None,
            "app_cpu_percent": None,
            "app_memory_bytes": 0,
            "error": str(e),
        }
