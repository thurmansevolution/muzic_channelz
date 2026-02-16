"""Backgrounds API: list, upload, placements."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.models import BackgroundTemplate, OverlayPlacement
from app.store import load_backgrounds, save_backgrounds


class UpdateBackgroundBody(BaseModel):
    """Request body for PUT /api/backgrounds/{id}."""
    name: str | None = None
    overlay_placements: list[OverlayPlacement] | None = None

router = APIRouter(prefix="/api/backgrounds", tags=["backgrounds"])


@router.get("", response_model=list[dict])
async def list_backgrounds() -> list[dict]:
    """List backgrounds: Stock, Stock (Dark Theme), then custom uploads."""
    list_bg = await load_backgrounds()
    out = [b.model_dump() for b in list_bg]
    stock = {
        "id": "stock",
        "name": "Stock",
        "is_stock": True,
        "image_path": "stock",
        "overlay_placements": [],
    }
    stock_dark = {
        "id": "stock-dark",
        "name": "Stock (Dark Theme)",
        "is_stock": True,
        "image_path": "stock-dark",
        "overlay_placements": [],
    }
    return [stock, stock_dark] + out


FEED_SIZE = (1920, 1080)


def _resize_background_to_feed(path: Path) -> None:
    """Resize image at path to 1920x1080 (fit and center on dark canvas). Overwrites the file."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = FEED_SIZE[0], FEED_SIZE[1]
    if img.size == (w, h):
        return
    canvas = Image.new("RGB", (w, h), (0x1a, 0x1a, 0x1a))
    img.thumbnail((w, h), Image.Resampling.LANCZOS)
    x = (w - img.width) // 2
    y = (h - img.height) // 2
    canvas.paste(img, (x, y))
    canvas.save(path, "PNG")


@router.post("/upload")
async def upload_background(
    file: UploadFile = File(...),
    name: str = "",
) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    bg_id = str(uuid.uuid4())[:8]
    filename = f"{bg_id}.png"
    path = (settings.backgrounds_dir or settings.data_dir / "backgrounds") / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    path.write_bytes(content)
    try:
        _resize_background_to_feed(path)
    except Exception:
        pass
    template = BackgroundTemplate(
        id=bg_id,
        name=name or file.filename or bg_id,
        is_stock=False,
        image_path=filename,
        overlay_placements=[],
    )
    backgrounds = await load_backgrounds()
    backgrounds.append(template)
    await save_backgrounds(backgrounds)
    return template.model_dump()


@router.put("/{background_id}")
async def update_background(background_id: str, body: UpdateBackgroundBody) -> dict:
    if background_id in ("stock", "stock-dark"):
        raise HTTPException(400, "Cannot update stock backgrounds")
    backgrounds = await load_backgrounds()
    for i, b in enumerate(backgrounds):
        if b.id == background_id:
            if body.name is not None:
                backgrounds[i].name = body.name
            if body.overlay_placements is not None:
                backgrounds[i].overlay_placements = list(body.overlay_placements)
            await save_backgrounds(backgrounds)
            return backgrounds[i].model_dump()
    raise HTTPException(404, "Background not found")


@router.delete("/{background_id}")
async def delete_background(background_id: str) -> dict:
    """Remove a custom background. Cannot delete stock backgrounds."""
    if background_id in ("stock", "stock-dark"):
        raise HTTPException(400, "Cannot remove stock backgrounds")
    backgrounds = await load_backgrounds()
    for i, b in enumerate(backgrounds):
        if b.id == background_id:
            root = settings.backgrounds_dir or settings.data_dir / "backgrounds"
            image_path = root / b.image_path
            if image_path.exists():
                try:
                    image_path.unlink()
                except OSError:
                    pass
            backgrounds.pop(i)
            await save_backgrounds(backgrounds)
            return {"deleted": background_id}
    raise HTTPException(404, "Background not found")


@router.get("/{background_id}/image")
async def get_background_image(background_id: str):
    """Serve the image file for a background. Stock dark is built-in; custom from store."""
    if background_id == "stock-dark":
        from app.overlay import ensure_stock_dark_background_png
        try:
            path = ensure_stock_dark_background_png()
            return FileResponse(path)
        except Exception:
            raise HTTPException(404, "Stock dark background not available")
    backgrounds = await load_backgrounds()
    bg = next((b for b in backgrounds if b.id == background_id), None)
    if not bg or bg.is_stock:
        raise HTTPException(404, "Background not found")
    root = settings.backgrounds_dir or settings.data_dir / "backgrounds"
    path = root / bg.image_path
    if not path.exists():
        raise HTTPException(404, "Image file not found")
    return FileResponse(path)
