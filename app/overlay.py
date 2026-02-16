"""Overlay: render stock background (SVG→PNG), resolve background image path, default placements."""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.models import OverlayPlacement

STOCK_BG_PNG_NAME = "stock-background.png"
STOCK_DARK_BG_PNG_NAME = "stock-background-dark.png"
STOCK_BG_SIZE = (1920, 1080)


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def _stock_png_path() -> Path:
    """Path to the canonical stock PNG (same file the Background Editor shows at /static/stock-background.png)."""
    return _static_dir() / STOCK_BG_PNG_NAME


def _stock_svg_path() -> Path:
    return _static_dir() / "stock-background.svg"


def _stock_dark_png_path() -> Path:
    return _static_dir() / STOCK_DARK_BG_PNG_NAME


def _stock_dark_svg_path() -> Path:
    return _static_dir() / "stock-background-dark.svg"


def ensure_stock_background_png() -> Path:
    """Return path to stock background PNG. Prefer app/static/stock-background.png so FFmpeg uses the same image as the Background Editor. If missing, render from SVG into that path (so both match)."""
    png_path = _stock_png_path()
    if png_path.exists():
        return png_path
    try:
        import cairosvg
        svg_path = _stock_svg_path()
        if not svg_path.exists():
            raise FileNotFoundError(f"Stock SVG not found: {svg_path}")
        png_path.parent.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=STOCK_BG_SIZE[0],
            output_height=STOCK_BG_SIZE[1],
        )
        return png_path
    except Exception:
        cache_dir = settings.data_dir / "streams" / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "stock-bg.png"
        if cache_path.exists():
            return cache_path
        try:
            import cairosvg
            cairosvg.svg2png(
                url=str(_stock_svg_path()),
                write_to=str(cache_path),
                output_width=STOCK_BG_SIZE[0],
                output_height=STOCK_BG_SIZE[1],
            )
            return cache_path
        except Exception:
            raise RuntimeError(
                "Could not render stock background. Install cairosvg and ensure stock-background.svg exists, or place stock-background.png in app/static/."
            ) from None


def _normalize_to_16_9(path: Path) -> None:
    """Resize image at path to 1920x1080 (fit and center on dark canvas). Overwrites the file."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    if img.size == (STOCK_BG_SIZE[0], STOCK_BG_SIZE[1]):
        return
    w, h = STOCK_BG_SIZE[0], STOCK_BG_SIZE[1]
    canvas = Image.new("RGB", (w, h), (0x1a, 0x1a, 0x1a))
    img.thumbnail((w, h), Image.Resampling.LANCZOS)
    x = (w - img.width) // 2
    y = (h - img.height) // 2
    canvas.paste(img, (x, y))
    canvas.save(path, "PNG")


def _render_dark_from_stock_png(source: Path, dest: Path) -> None:
    """Generate a dark-theme PNG from the stock: same-ish brightness, blues→dark greys, black→lighter grey (app dark mode style)."""
    from PIL import Image
    img = Image.open(source).convert("RGB")
    img = img.resize((STOCK_BG_SIZE[0], STOCK_BG_SIZE[1]), Image.Resampling.LANCZOS)
    grey = img.convert("L")
    lut = [min(255, int(round(0.28 * 255 + 0.72 * i))) for i in range(256)]
    grey = grey.point(lut, mode="L")
    out = grey.convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, "PNG")


def ensure_stock_dark_background_png() -> Path:
    """Return path to stock dark theme PNG (16:9, 1280x720). Use app/static/stock-background-dark.png if present; else generate from light stock or SVG."""
    png_path = _stock_dark_png_path()
    if png_path.exists():
        try:
            _normalize_to_16_9(png_path)
        except Exception:
            pass
        return png_path
    stock_png = _stock_png_path()
    svg_path = _stock_dark_svg_path()
    if stock_png.exists():
        try:
            _render_dark_from_stock_png(stock_png, png_path)
            return png_path
        except Exception:
            pass
    if png_path.exists() and svg_path.exists():
        try:
            if svg_path.stat().st_mtime <= png_path.stat().st_mtime:
                return png_path
        except OSError:
            pass
        png_path.unlink(missing_ok=True)
    try:
        import cairosvg
        if not svg_path.exists():
            raise FileNotFoundError(f"Stock dark SVG not found: {svg_path}")
        png_path.parent.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=STOCK_BG_SIZE[0],
            output_height=STOCK_BG_SIZE[1],
        )
        return png_path
    except Exception:
        cache_dir = settings.data_dir / "streams" / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "stock-bg-dark.png"
        if cache_path.exists():
            return cache_path
        try:
            import cairosvg
            cairosvg.svg2png(
                url=str(_stock_dark_svg_path()),
                write_to=str(cache_path),
                output_width=STOCK_BG_SIZE[0],
                output_height=STOCK_BG_SIZE[1],
            )
            return cache_path
        except Exception:
            raise RuntimeError(
                "Could not render stock dark background. Place stock-background.png in app/static/ or ensure stock-background-dark.svg exists."
            ) from None


def default_overlay_placements() -> list[OverlayPlacement]:
    """Default positions: channel name upper left; artist image center aligned just below first line of bio; song/artist below image with extra gap between them; bio center-right."""
    return [
        OverlayPlacement(key="channel_name", x=40, y=40, width=0, height=0, font_size=28, anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="song_title", x=80, y=540, width=0, height=0, font_size=34, anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="artist_name", x=80, y=625, width=0, height=0, font_size=28, anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="artist_bio", x=500, y=280, width=0, height=0, font_size=24, anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="artist_image", x=135, y=195, width=230, height=230, font_size=0, anchor="nw"),
    ]


def get_placement(placements: list[OverlayPlacement], key: str) -> OverlayPlacement | None:
    """Return placement for key, or None."""
    for p in placements:
        if p.key == key:
            return p
    return None
