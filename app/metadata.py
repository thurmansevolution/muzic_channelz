"""Fetch artist metadata (bio/summary) from MusicBrainz, Last.fm, etc. for overlay."""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import quote

import httpx

from app.models import AdminState

USER_AGENT = "muzic-channelz/1.0 (https://github.com/your-org/muzic-channelz)"
MAX_BIO_CHARS = 200


def _truncate(s: str, max_len: int = MAX_BIO_CHARS) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rsplit(" ", 1)[0] + "…" if " " in s[:max_len] else s[: max_len - 1] + "…"


def _is_type_only_bio(s: str) -> bool:
    """True if s looks like MusicBrainz type/country only (e.g. 'Group (US)'), not a real biography."""
    if not s or len(s) > 80:
        return len(s or "") <= 80
    s = (s or "").strip()
    pattern = r"^(Group|Person|Orchestra|Choir|Character|Other)(\s*·\s*[^·]+)?\s*(\([A-Z]{2}\))?$"
    return bool(re.match(pattern, s, re.IGNORECASE))


async def _fetch_musicbrainz(artist: str) -> str:
    """MusicBrainz: no API key. Search artist, return type + disambiguation. Not used as bio when it's only type/country."""
    if not (artist or "").strip():
        return ""
    url = "https://musicbrainz.org/ws/2/artist/"
    params = {"query": artist.strip(), "fmt": "json", "limit": "1"}
    try:
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return ""
    artists = data.get("artists") or []
    if not artists:
        return ""
    a = artists[0]
    parts = []
    if a.get("type"):
        parts.append(a["type"])
    if a.get("disambiguation"):
        parts.append(a["disambiguation"])
    if a.get("country"):
        parts.append(f"({a['country']})")
    if not parts:
        return ""
    out = _truncate(" · ".join(parts))
    if _is_type_only_bio(out):
        return ""
    return out


async def _fetch_theaudiodb(artist: str, api_key: str, base_url: str = "") -> str:
    """TheAudioDB: search artist, return English biography. Free API key at theaudiodb.com."""
    if not (artist or "").strip():
        return ""
    key = (api_key or "").strip() or "2"
    base = (base_url or "https://www.theaudiodb.com/api/v1/json").rstrip("/")
    url = f"{base}/{key}/search.php?s={quote(artist.strip())}"
    try:
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return ""
    artists = data.get("artists") or []
    if not artists:
        return ""
    a = artists[0] if isinstance(artists[0], dict) else {}
    bio = (a.get("strBiographyEN") or a.get("strBiography") or "").strip()
    if not bio:
        return ""
    bio = re.sub(r"<[^>]+>", "", bio)
    return _truncate(bio)


async def _fetch_lastfm(artist: str, api_key: str, base_url: str = "") -> str:
    """Last.fm artist.getInfo: returns bio summary. Requires free API key."""
    if not (artist or "").strip() or not (api_key or "").strip():
        return ""
    base = (base_url or "https://ws.audioscrobbler.com/2.0/").rstrip("/")
    url = f"{base}/?method=artist.getinfo&artist={quote(artist.strip())}&api_key={api_key.strip()}&format=json"
    try:
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return ""
    try:
        bio = (data.get("artist") or {}).get("bio") or {}
        summary = (bio.get("summary") or "").strip()
        if not summary:
            return ""
        summary = re.sub(r"<[^>]+>", "", summary)
        return _truncate(summary)
    except Exception:
        return ""


async def fetch_artist_bio(
    artist: str,
    state: AdminState,
    log_cb: Callable[[str], None] | None = None,
) -> str:
    """Return a short artist bio/summary; uses and populates metadata cache to reduce API usage."""
    artist = (artist or "").strip()
    if not artist or artist == "—":
        if log_cb:
            log_cb("artist empty or placeholder, skip metadata")
        return "—"
    from app.metadata_cache import get_cached, set_cached
    cached = get_cached(artist)
    if cached is not None and cached.get("bio") is not None:
        if log_cb:
            log_cb(f"artist bio cache hit: {artist!r}")
        return cached["bio"]
    providers = list(getattr(state, "metadata_providers", None) or [])
    providers = sorted(providers, key=lambda p: (0 if (p.name or "").strip() == "Last.fm" else 1))
    if not providers and log_cb:
        log_cb("no metadata providers configured")
    for p in providers:
        name = (p.name or "").strip()
        if not name:
            continue
        if name == "MusicBrainz":
            out = await _fetch_musicbrainz(artist)
            if log_cb:
                log_cb(f"MusicBrainz artist={artist!r} -> {out!r}" if out else f"MusicBrainz artist={artist!r} -> (no result)")
            if out:
                set_cached(artist, bio=out)
                return out
        elif name == "TheAudioDB":
            key = (p.api_key_or_token or "").strip()
            base = (getattr(p, "base_url", None) or "").strip()
            out = await _fetch_theaudiodb(artist, key or "2", base or None)
            if log_cb:
                log_cb(f"TheAudioDB artist={artist!r} -> {out!r}" if out else f"TheAudioDB artist={artist!r} -> (no result)")
            if out:
                set_cached(artist, bio=out)
                return out
        elif name == "Last.fm":
            key = (p.api_key_or_token or "").strip()
            base = (getattr(p, "base_url", None) or "").strip()
            if key:
                out = await _fetch_lastfm(artist, key, base or None)
                if log_cb:
                    log_cb(f"Last.fm artist={artist!r} -> {out!r}" if out else f"Last.fm artist={artist!r} -> (no result)")
                if out:
                    set_cached(artist, bio=out)
                    return out
            elif log_cb:
                log_cb("Last.fm configured but API key empty")
    if log_cb:
        log_cb(f"no bio for artist={artist!r}")
    out = "—"
    set_cached(artist, bio=out)
    return out


async def fetch_artist_image_url_musicbrainz(
    artist: str,
    log_cb: Callable[[str], None] | None = None,
) -> str:
    """Return URL of artist image from MusicBrainz (artist relations with type 'image'). No API key required."""
    artist = (artist or "").strip()
    if not artist or artist == "—":
        return ""
    search_url = "https://musicbrainz.org/ws/2/artist/"
    params = {"query": artist, "fmt": "json", "limit": "1"}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(search_url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if log_cb:
            log_cb(f"MusicBrainz artist image search error: {e}")
        return ""
    artists = data.get("artists") or []
    if not artists:
        return ""
    mbid = (artists[0].get("id") or "").strip()
    if not mbid:
        return ""
    lookup_url = f"https://musicbrainz.org/ws/2/artist/{mbid}"
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(lookup_url, params={"inc": "url-rels", "fmt": "json"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if log_cb:
            log_cb(f"MusicBrainz artist lookup error: {e}")
        return ""
    relations = data.get("relations") or []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        t = rel.get("type")
        type_name = (t if isinstance(t, str) else (t.get("name") if isinstance(t, dict) else "")) or ""
        if type_name.lower() != "image":
            continue
        url_obj = rel.get("url")
        if isinstance(url_obj, dict):
            resource = (url_obj.get("resource") or "").strip()
            if resource and resource.startswith("http"):
                if log_cb:
                    log_cb(f"MusicBrainz artist image={artist!r} -> {resource[:60]}…")
                return resource
    if log_cb:
        log_cb(f"MusicBrainz no image relation for {artist!r}")
    return ""


async def fetch_artist_image_url_theaudiodb(
    artist: str,
    state: AdminState,
    log_cb: Callable[[str], None] | None = None,
) -> str:
    """Return URL of artist image from TheAudioDB (strArtistThumb / strArtistLogo). Requires configured TheAudioDB provider."""
    artist = (artist or "").strip()
    if not artist or artist == "—":
        return ""
    providers = list(getattr(state, "metadata_providers", None) or [])
    for p in providers:
        if (p.name or "").strip() != "TheAudioDB":
            continue
        key = (p.api_key_or_token or "").strip() or "2"
        base = (getattr(p, "base_url", None) or "").strip() or "https://www.theaudiodb.com/api/v1/json"
        base = base.rstrip("/")
        url = f"{base}/{key}/search.php?s={quote(artist)}"
        try:
            async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            if log_cb:
                log_cb(f"TheAudioDB artist image error: {e}")
            continue
        artists = data.get("artists") or []
        if not artists or not isinstance(artists[0], dict):
            if log_cb:
                log_cb(f"TheAudioDB no artist result for {artist!r}")
            return ""
        a = artists[0]
        for field in ("strArtistThumb", "strArtistLogo", "strArtistCutout", "strArtistBanner"):
            u = (a.get(field) or "").strip()
            if u and u.startswith("http"):
                if log_cb:
                    log_cb(f"TheAudioDB artist image={artist!r} -> {field}")
                return u
        if log_cb:
            log_cb(f"TheAudioDB no image for {artist!r}")
        return ""
    return ""


async def fetch_artist_image_url(
    artist: str,
    state: AdminState,
    log_cb: Callable[[str], None] | None = None,
) -> str:
    """Return URL of artist image (or file:// path to cached image). Use cache if present, else fetch and cache."""
    artist = (artist or "").strip()
    if not artist or artist == "—":
        return ""
    from app.metadata_cache import get_cached, set_cached
    cached = get_cached(artist)
    if cached is not None:
        if cached.get("image_path") and cached["image_path"].exists():
            if log_cb:
                log_cb(f"artist image cache hit (file): {artist!r}")
            return "file://" + str(cached["image_path"])
        if "image_url" in cached:
            image_url = cached.get("image_url") or ""
            if image_url == "":
                if log_cb:
                    log_cb(f"artist image cache hit (no image): {artist!r}")
                return ""
            if image_url.startswith("http"):
                if log_cb:
                    log_cb(f"artist image cache hit (url): {artist!r}")
                return image_url
    url = await fetch_artist_image_url_theaudiodb(artist, state, log_cb=log_cb)
    if url:
        set_cached(artist, image_url=url)
        return url
    url = await fetch_artist_image_url_musicbrainz(artist, log_cb=log_cb)
    if url:
        set_cached(artist, image_url=url)
        return url
    providers = list(getattr(state, "metadata_providers", None) or [])
    for p in providers:
        if (p.name or "").strip() != "Last.fm":
            continue
        key = (p.api_key_or_token or "").strip()
        if not key:
            continue
        base = (getattr(p, "base_url", None) or "").strip() or "https://ws.audioscrobbler.com/2.0/"
        base = base.rstrip("/")
        api_url = f"{base}/?method=artist.getinfo&artist={quote(artist)}&api_key={key}&format=json"
        try:
            async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": USER_AGENT}) as client:
                r = await client.get(api_url)
                r.raise_for_status()
                data = r.json()
        except Exception:
            continue
        try:
            LASTFM_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"
            images = (data.get("artist") or {}).get("image") or []
            for size in ("extralarge", "large", "medium", "small"):
                for img in images:
                    if isinstance(img, dict) and img.get("size") == size:
                        u = (img.get("#text") or img.get("url") or "").strip()
                        if u and u.startswith("http") and LASTFM_PLACEHOLDER_HASH not in u:
                            if log_cb:
                                log_cb(f"Last.fm artist image={artist!r} -> {size}")
                            set_cached(artist, image_url=u)
                            return u
                        if u and LASTFM_PLACEHOLDER_HASH in u and log_cb:
                            log_cb(f"Last.fm artist image={artist!r} -> skipped (placeholder)")
        except Exception:
            pass
    if log_cb and artist:
        log_cb(f"no artist image for {artist!r}")
    return ""
