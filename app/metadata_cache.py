"""Local cache for artist metadata (bio + image) to reduce API calls (e.g. TheAudioDB 30/min)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.config import settings

CACHE_DIR_NAME = "metadata_cache"
INDEX_FILENAME = "index.json"
IMAGES_DIR_NAME = "images"


def _cache_root() -> Path:
    root = settings.data_dir / CACHE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _artist_key(artist: str) -> str:
    """Normalize artist name for cache key (case-insensitive, single spaces)."""
    if not artist:
        return ""
    return re.sub(r"\s+", " ", artist.strip().lower())


def _image_filename(artist_key: str) -> str:
    """Safe filename for cached image (same key => same file)."""
    if not artist_key:
        return ""
    return hashlib.sha256(artist_key.encode("utf-8")).hexdigest()[:32] + ".png"


def get_cached(artist: str) -> dict[str, Any] | None:
    """
    Return cached metadata for artist if present: { "bio": str | None, "image_url": str, "image_path": Path }.
    image_path is the path to cached image file if it exists. Caller can use bio and, for image, copy image_path
    or use image_url. Returns None if no cache entry.
    """
    key = _artist_key(artist)
    if not key:
        return None
    root = _cache_root()
    index_path = root / INDEX_FILENAME
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = data.get(key)
    if not isinstance(entry, dict):
        return None
    bio = entry.get("bio")
    img_name = _image_filename(key)
    image_path = (root / IMAGES_DIR_NAME / img_name) if img_name else None
    if image_path and not image_path.exists():
        image_path = None
    result: dict[str, Any] = {"bio": bio, "image_path": image_path}
    if "image_url" in entry and entry.get("image_url"):
        result["image_url"] = entry["image_url"]
    return result


def set_cached(artist: str, *, bio: str | None = None, image_url: str | None = None) -> None:
    """Store or update cache entry for artist (bio and/or image_url). Does not write image file; use save_cached_image for that."""
    key = _artist_key(artist)
    if not key:
        return
    root = _cache_root()
    index_path = root / INDEX_FILENAME
    data: dict[str, dict[str, Any]] = {}
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if not isinstance(data, dict):
        data = {}
    entry = data.setdefault(key, {"bio": None, "image_url": ""})
    if bio is not None:
        entry["bio"] = bio
    if image_url is not None:
        entry["image_url"] = image_url
    try:
        index_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def save_cached_image(artist: str, source_path: Path) -> bool:
    """Copy image from source_path into cache for artist. Returns True on success."""
    key = _artist_key(artist)
    if not key:
        return False
    root = _cache_root()
    images_dir = root / IMAGES_DIR_NAME
    images_dir.mkdir(parents=True, exist_ok=True)
    dest = images_dir / _image_filename(key)
    try:
        shutil.copy2(source_path, dest)
        return True
    except OSError:
        return False


def clear_cache() -> tuple[bool, str]:
    """
    Remove all cached metadata (index + image files). Returns (success, message).
    """
    root = _cache_root()
    try:
        if (root / INDEX_FILENAME).exists():
            (root / INDEX_FILENAME).unlink()
        images_dir = root / IMAGES_DIR_NAME
        if images_dir.exists():
            shutil.rmtree(images_dir)
        return True, "Metadata cache cleared."
    except OSError as e:
        return False, f"Could not clear cache: {e}"
