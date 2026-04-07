"""Persistent store for admin state and backgrounds (JSON + files)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import settings
from app.models import AdminState, BackgroundTemplate

STATE_FILE = "admin_state.json"
BACKGROUNDS_INDEX = "backgrounds_index.json"

# Short-lived read cache: avoids redundant disk reads when load_admin_state()
# is called several times within a single request cycle (e.g. channel startup).
_state_cache: AdminState | None = None
_state_cache_at: float = 0.0
_STATE_CACHE_TTL = 2.0


def _state_path() -> Path:
    return settings.data_dir / STATE_FILE


def _backgrounds_index_path() -> Path:
    assert settings.backgrounds_dir
    return settings.backgrounds_dir / BACKGROUNDS_INDEX


async def load_admin_state() -> AdminState:
    global _state_cache, _state_cache_at
    now = time.monotonic()
    if _state_cache is not None and (now - _state_cache_at) < _STATE_CACHE_TTL:
        return _state_cache
    path = _state_path()
    if not path.exists():
        result = AdminState()
    else:
        data = path.read_text(encoding="utf-8")
        result = AdminState.model_validate(json.loads(data))
    _state_cache = result
    _state_cache_at = now
    return result


async def save_admin_state(state: AdminState) -> None:
    global _state_cache, _state_cache_at
    _state_path().write_text(state.model_dump_json(indent=2), encoding="utf-8")
    _state_cache = state
    _state_cache_at = time.monotonic()


async def load_backgrounds() -> list[BackgroundTemplate]:
    path = _backgrounds_index_path()
    if not path.exists():
        return []
    data = path.read_text(encoding="utf-8")
    raw = json.loads(data)
    return [BackgroundTemplate.model_validate(b) for b in raw]


async def save_backgrounds(backgrounds: list[BackgroundTemplate]) -> None:
    path = _backgrounds_index_path()
    path.write_text(
        json.dumps([b.model_dump() for b in backgrounds], indent=2),
        encoding="utf-8",
    )
