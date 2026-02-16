"""Now-playing: fetch Azuracast and write overlay text (and optional art, artist bio) for a channel."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx

from app.models import AdminState, AzuracastStation, Channel


def _station_for_channel(channel: Channel, state: AdminState) -> AzuracastStation | None:
    want = (channel.azuracast_station_id or "").strip()
    if not want:
        return None
    for st in state.azuracast_stations:
        name = (st.name or "").strip()
        shortcode = (st.station_shortcode or "").strip()
        if not st.base_url or not shortcode:
            continue
        if name == want or shortcode == want:
            return st
    return None


def _escape_drawtext(s: str) -> str:
    """Escape for FFmpeg drawtext: backslash and single quotes."""
    if not s:
        return ""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")


def _wrap_text(text: str, max_chars_per_line: int = 48) -> str:
    """Wrap text into lines of at most max_chars_per_line (break at spaces). For drawtext multiline display."""
    if not text or max_chars_per_line <= 0:
        return text or ""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= max_chars_per_line:
        return text
    lines: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_chars_per_line:
            lines.append(rest.strip())
            break
        chunk = rest[: max_chars_per_line + 1]
        last_space = chunk.rfind(" ")
        if last_space > 0:
            lines.append(rest[:last_space].strip())
            rest = rest[last_space + 1 :].lstrip()
        else:
            lines.append(rest[:max_chars_per_line])
            rest = rest[max_chars_per_line:].lstrip()
    return "\n".join(lines)


async def _fetch_now_playing(station: AzuracastStation) -> dict | None:
    url = f"{station.base_url.rstrip('/')}/api/nowplaying/{station.station_shortcode}"
    headers = {}
    if station.api_key:
        headers["Authorization"] = f"Bearer {station.api_key}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers or None)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


def _parse_now_playing(data: dict) -> tuple[str, str, str]:
    """Return (title, artist, art_url). Tries multiple keys for art (Azuracast can use art, album_art, etc.)."""
    try:
        np = data.get("now_playing") or {}
        song = np.get("song") or {}
        title = (song.get("title") or song.get("text") or "").strip() or "—"
        artist = (song.get("artist") or "").strip() or "—"
        art_url = ""
        for key in ("art", "album_art", "artwork", "image"):
            v = song.get(key)
            if isinstance(v, str) and v.strip():
                art_url = v.strip()
                break
            if isinstance(v, dict):
                u = (v.get("url") or v.get("#text") or v.get("value") or "").strip()
                if u:
                    art_url = u
                    break
        return (title, artist, art_url)
    except Exception:
        return ("—", "—", "")


def _default_art_path() -> Path:
    """Path to the default muzic channelz logo used when no artist image is found."""
    return Path(__file__).resolve().parent.parent / "frontend" / "public" / "logo.png"


async def write_now_playing_files(
    stream_dir: Path,
    channel: Channel,
    state: AdminState,
) -> tuple[str, str]:
    """Fetch now playing and metadata (bio + art), then write all overlay files together so they update in sync."""
    station = _station_for_channel(channel, state)
    if not station:
        stream_dir.mkdir(parents=True, exist_ok=True)
        stream_dir.joinpath("song.txt").write_text("—", encoding="utf-8")
        stream_dir.joinpath("artist.txt").write_text("—", encoding="utf-8")
        stream_dir.joinpath("bio.txt").write_text("—", encoding="utf-8")
        default_art = _default_art_path()
        if default_art.exists():
            import shutil
            shutil.copy2(default_art, stream_dir / "art.png")
        return ("—", "—")
    data = await _fetch_now_playing(station)
    title, artist, _ = _parse_now_playing(data) if data else ("—", "—", "")
    stream_dir.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        try:
            from app.ffmpeg_runner import append_metadata_log
            append_metadata_log(channel.id, msg)
        except Exception:
            pass

    bio = "—"
    if artist and artist != "—":
        try:
            from app.metadata import fetch_artist_bio
            bio = await fetch_artist_bio(artist, state, log_cb=_log)
        except Exception as e:
            _log(f"metadata error: {e}")

    art_path = stream_dir / "art.png"
    art_url = ""
    if artist and artist != "—":
        try:
            from app.metadata import fetch_artist_image_url
            art_url = await fetch_artist_image_url(artist, state, log_cb=_log)
            if art_url:
                _log(f"artist image: {art_url[:80]}{'…' if len(art_url) > 80 else ''}")
        except Exception as e:
            _log(f"artist image error: {e}")

    art_resolved = False
    if art_url:
        try:
            if art_url.startswith("file://"):
                src = Path(art_url.removeprefix("file://"))
                if src.exists():
                    import shutil
                    shutil.copy2(src, art_path)
                    _log("wrote art.png OK (from cache)")
                    art_resolved = True
                else:
                    _log("cached image file missing")
            else:
                async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                    r = await client.get(art_url)
                    if r.status_code == 200:
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(r.content))
                        if img.mode not in ("RGB", "RGBA"):
                            img = img.convert("RGB")
                        tmp = art_path.with_name(art_path.name + ".tmp")
                        img.save(tmp, "PNG")
                        os.replace(tmp, art_path)
                        _log("wrote art.png OK")
                        from app.metadata_cache import save_cached_image
                        if not save_cached_image(artist, art_path):
                            _log("cache save_cached_image failed")
                        art_resolved = True
                    else:
                        _log(f"art download failed: HTTP {r.status_code}")
        except Exception as e:
            _log(f"art download error: {e}")
    if not art_resolved:
        default_art = _default_art_path()
        if default_art.exists():
            import shutil
            shutil.copy2(default_art, art_path)
            _log("art: using default logo (no artist image)")
        else:
            _log("no art source — art.png unchanged")

    await asyncio.sleep(1.0)
    stream_dir.joinpath("song.txt").write_text(_wrap_text(title, 56), encoding="utf-8")
    stream_dir.joinpath("artist.txt").write_text(artist, encoding="utf-8")
    stream_dir.joinpath("bio.txt").write_text(_wrap_text(bio, 48), encoding="utf-8")
    return (title, artist)


async def now_playing_loop(
    channel_id: str,
    stream_dir: Path,
    load_state: callable,
    interval_seconds: float = 10.0,
    stop_event: asyncio.Event | None = None,
    on_song_change: callable | None = None,
) -> None:
    """Background task: periodically update song/artist (and art) files for a channel."""
    stop = stop_event or asyncio.Event()
    prev_title: str | None = None
    prev_artist: str | None = None
    while not stop.is_set():
        try:
            state = await load_state()
            ch = next((c for c in state.channels if c.id == channel_id), None)
            if ch:
                title, artist = await write_now_playing_files(stream_dir, ch, state)
                if on_song_change is not None and (prev_title is not None or prev_artist is not None):
                    if title != prev_title or artist != prev_artist:
                        try:
                            await on_song_change()
                        except Exception:
                            pass
                prev_title, prev_artist = title, artist
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
