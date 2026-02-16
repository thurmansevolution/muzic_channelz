"""Persistent store for admin state and backgrounds (JSON + files)."""
from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.models import AdminState, BackgroundTemplate

STATE_FILE = "admin_state.json"
BACKGROUNDS_INDEX = "backgrounds_index.json"


def _state_path() -> Path:
    return settings.data_dir / STATE_FILE


def _backgrounds_index_path() -> Path:
    assert settings.backgrounds_dir
    return settings.backgrounds_dir / BACKGROUNDS_INDEX


async def load_admin_state() -> AdminState:
    path = _state_path()
    if not path.exists():
        return AdminState()
    data = path.read_text(encoding="utf-8")
    return AdminState.model_validate(json.loads(data))


async def save_admin_state(state: AdminState) -> None:
    _state_path().write_text(state.model_dump_json(indent=2), encoding="utf-8")


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
