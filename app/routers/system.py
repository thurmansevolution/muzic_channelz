"""System API: resource usage for Home dashboard."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/system", tags=["system"])


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
