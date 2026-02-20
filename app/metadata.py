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


async def _fetch_discogs_bio(artist: str, token: str, base_url: str = "") -> str:
    """Discogs: search artist, then GET artist/{id} for profile (bio). Token from discogs.com/settings/developers."""
    if not (artist or "").strip() or not (token or "").strip():
        return ""
    base = (base_url or "https://api.discogs.com").rstrip("/")
    search_url = f"{base}/database/search"
    headers = {"User-Agent": USER_AGENT, "Authorization": f"Discogs token={token.strip()}"}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            r = await client.get(search_url, params={"q": artist.strip(), "type": "artist", "per_page": "1"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return ""
    results = data.get("results") or []
    if not results or not isinstance(results[0], dict):
        return ""
    artist_id = results[0].get("id")
    if not artist_id:
        return ""
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            r = await client.get(f"{base}/artists/{artist_id}")
            r.raise_for_status()
            data = r.json()
    except Exception:
        return ""
    profile = (data.get("profile") or "").strip()
    if not profile:
        return ""
    profile = re.sub(r"<[^>]+>", "", profile)
    return _truncate(profile)


async def _fetch_genius_bio(artist: str, api_key: str, base_url: str = "") -> str:
    """Genius: search, then GET artists/{id} for description. API key from genius.com/api-clients."""
    if not (artist or "").strip() or not (api_key or "").strip():
        return ""
    base = (base_url or "https://api.genius.com").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key.strip()}", "User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            r = await client.get(f"{base}/search", params={"q": artist.strip()})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return ""
    hits = (data.get("response") or {}).get("hits") or []
    for h in hits:
        if not isinstance(h, dict):
            continue
        res = h.get("result") or {}
        primary = res.get("primary_artist") or {}
        artist_id = primary.get("id")
        if not artist_id:
            continue
        try:
            async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
                r = await client.get(f"{base}/artists/{artist_id}")
                r.raise_for_status()
                adata = r.json()
        except Exception:
            continue
        artist_data = (adata.get("response") or {}).get("artist") or {}
        desc = (artist_data.get("description") or artist_data.get("description_annotation", {}).get("plain") or "").strip()
        if desc:
            desc = re.sub(r"<[^>]+>", "", desc)
            return _truncate(desc)
        break
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
        elif name == "Discogs":
            key = (p.api_key_or_token or "").strip()
            base = (getattr(p, "base_url", None) or "").strip()
            if key:
                out = await _fetch_discogs_bio(artist, key, base or None)
                if log_cb and out:
                    log_cb(f"Discogs artist={artist!r} -> bio")
                if out:
                    set_cached(artist, bio=out)
                    return out
        elif name == "Genius":
            key = (p.api_key_or_token or "").strip()
            base = (getattr(p, "base_url", None) or "").strip()
            if key:
                out = await _fetch_genius_bio(artist, key, base or None)
                if log_cb and out:
                    log_cb(f"Genius artist={artist!r} -> bio")
                if out:
                    set_cached(artist, bio=out)
                    return out
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


async def _image_url_deezer(artist: str, log_cb: Callable[[str], None] | None = None) -> str:
    """Deezer search/artist: no API key. Returns picture_big or picture_xl."""
    if not (artist or "").strip():
        return ""
    url = "https://api.deezer.com/search/artist"
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url, params={"q": artist.strip(), "limit": "1"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if log_cb:
            log_cb(f"Deezer image error: {e}")
        return ""
    items = data.get("data") or []
    if not items or not isinstance(items[0], dict):
        return ""
    a = items[0]
    for key in ("picture_xl", "picture_big", "picture_medium"):
        u = (a.get(key) or "").strip()
        if u and u.startswith("http"):
            if log_cb:
                log_cb(f"Deezer artist image={artist!r}")
            return u
    return ""


async def _image_url_itunes(artist: str, log_cb: Callable[[str], None] | None = None) -> str:
    """iTunes Search API: no key. Returns artworkUrl100 from first artist result."""
    if not (artist or "").strip():
        return ""
    url = "https://itunes.apple.com/search"
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url, params={"term": artist.strip(), "entity": "allArtist", "limit": "1"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if log_cb:
            log_cb(f"iTunes image error: {e}")
        return ""
    results = data.get("results") or []
    if not results or not isinstance(results[0], dict):
        return ""
    u = (results[0].get("artworkUrl100") or results[0].get("artworkUrl60") or "").strip()
    if u and u.startswith("http"):
        if log_cb:
            log_cb(f"iTunes artist image={artist!r}")
        return u.replace("100x100", "600x600") if "100x100" in u else u
    return ""


async def _image_url_spotify(artist: str, client_id: str, client_secret: str, log_cb: Callable[[str], None] | None = None) -> str:
    """Spotify Web API: client credentials, then search artist, use first image. Store 'client_id:client_secret' in api_key_or_token."""
    if not (artist or "").strip() or ":" not in f"{client_id}:{client_secret}":
        return ""
    import base64
    creds = base64.b64encode(f"{client_id.strip()}:{client_secret.strip()}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            token = (r.json().get("access_token") or "").strip()
    except Exception as e:
        if log_cb:
            log_cb(f"Spotify token error: {e}")
        return ""
    if not token:
        return ""
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}) as client:
            r = await client.get("https://api.spotify.com/v1/search", params={"q": artist.strip(), "type": "artist", "limit": "1"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if log_cb:
            log_cb(f"Spotify search error: {e}")
        return ""
    artists = (data.get("artists") or {}).get("items") or []
    if not artists or not isinstance(artists[0], dict):
        return ""
    imgs = (artists[0].get("images") or [])
    for img in imgs:
        if isinstance(img, dict):
            u = (img.get("url") or "").strip()
            if u and u.startswith("http"):
                if log_cb:
                    log_cb(f"Spotify artist image={artist!r}")
                return u
    return ""


async def _image_url_discogs(artist: str, token: str, base_url: str = "", log_cb: Callable[[str], None] | None = None) -> str:
    """Discogs: search artist, use cover_image or thumb from first result."""
    if not (artist or "").strip() or not (token or "").strip():
        return ""
    base = (base_url or "https://api.discogs.com").rstrip("/")
    headers = {"User-Agent": USER_AGENT, "Authorization": f"Discogs token={token.strip()}"}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            r = await client.get(f"{base}/database/search", params={"q": artist.strip(), "type": "artist", "per_page": "1"})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if log_cb:
            log_cb(f"Discogs image error: {e}")
        return ""
    results = data.get("results") or []
    if not results or not isinstance(results[0], dict):
        return ""
    a = results[0]
    for key in ("cover_image", "thumb"):
        u = (a.get(key) or "").strip()
        if u and u.startswith("http"):
            if log_cb:
                log_cb(f"Discogs artist image={artist!r}")
            return u
    return ""


async def _image_url_genius(artist: str, api_key: str, base_url: str = "", log_cb: Callable[[str], None] | None = None) -> str:
    """Genius: search, use primary_artist.image_url from first hit."""
    if not (artist or "").strip() or not (api_key or "").strip():
        return ""
    base = (base_url or "https://api.genius.com").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key.strip()}", "User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            r = await client.get(f"{base}/search", params={"q": artist.strip()})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if log_cb:
            log_cb(f"Genius image error: {e}")
        return ""
    hits = (data.get("response") or {}).get("hits") or []
    for h in hits:
        if not isinstance(h, dict):
            continue
        res = h.get("result") or {}
        primary = res.get("primary_artist") or {}
        u = (primary.get("image_url") or "").strip()
        if u and u.startswith("http"):
            if log_cb:
                log_cb(f"Genius artist image={artist!r}")
            return u
        break
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
        name = (p.name or "").strip()
        if not name:
            continue
        key = (p.api_key_or_token or "").strip()
        base = (getattr(p, "base_url", None) or "").strip()
        if name == "Last.fm":
            if not key:
                continue
            base = base or "https://ws.audioscrobbler.com/2.0/"
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
            except Exception:
                pass
        elif name == "Deezer":
            url = await _image_url_deezer(artist, log_cb=log_cb)
            if url:
                set_cached(artist, image_url=url)
                return url
        elif name == "iTunes":
            url = await _image_url_itunes(artist, log_cb=log_cb)
            if url:
                set_cached(artist, image_url=url)
                return url
        elif name == "Spotify":
            if ":" in key:
                cid, csec = key.split(":", 1)
                url = await _image_url_spotify(artist, cid.strip(), csec.strip(), log_cb=log_cb)
                if url:
                    set_cached(artist, image_url=url)
                    return url
        elif name == "Discogs" and key:
            url = await _image_url_discogs(artist, key, base or None, log_cb=log_cb)
            if url:
                set_cached(artist, image_url=url)
                return url
        elif name == "Genius" and key:
            url = await _image_url_genius(artist, key, base or None, log_cb=log_cb)
            if url:
                set_cached(artist, image_url=url)
                return url
    if log_cb and artist:
        log_cb(f"no artist image for {artist!r}")
    return ""
