"""Azuracast Now Playing API client."""
from __future__ import annotations

import httpx
from app.models import AzuracastStation


async def fetch_now_playing(station: AzuracastStation) -> dict | None:
    """Fetch now playing JSON for one station. Returns None on error."""
    if not station.base_url or not station.station_shortcode:
        return None
    url = f"{station.base_url.rstrip('/')}/api/nowplaying/{station.station_shortcode}"
    headers = {}
    if station.api_key:
        headers["Authorization"] = f"Bearer {station.api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers or None)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None
