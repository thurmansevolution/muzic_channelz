"""Overlay: render stock background (SVG→PNG), resolve background image path, default placements."""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.models import OverlayPlacement

STOCK_BG_PNG_NAME = "stock-background.png"
STOCK_DARK_BG_PNG_NAME = "stock-background-dark.png"


def _output_size() -> tuple[int, int]:
    """Output resolution (width, height) for streams and stock backgrounds."""
    return (settings.output_width, settings.output_height)


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
        w, h = _output_size()
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=w,
            output_height=h,
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
            w, h = _output_size()
            cairosvg.svg2png(
                url=str(_stock_svg_path()),
                write_to=str(cache_path),
                output_width=w,
                output_height=h,
            )
            return cache_path
        except Exception:
            raise RuntimeError(
                "Could not render stock background. Install cairosvg and ensure stock-background.svg exists, or place stock-background.png in app/static/."
            ) from None


def _normalize_to_16_9(path: Path) -> None:
    """Resize image at path to output size (fit and center on dark canvas). Overwrites the file."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = _output_size()
    if img.size == (w, h):
        return
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
    w, h = _output_size()
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    grey = img.convert("L")
    lut = [min(255, int(round(0.28 * 255 + 0.72 * i))) for i in range(256)]
    grey = grey.point(lut, mode="L")
    out = grey.convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, "PNG")


def ensure_stock_dark_background_png() -> Path:
    """Return path to stock dark theme PNG (16:9, at configured output size). Use app/static/stock-background-dark.png if present; else generate from light stock or SVG."""
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
        w, h = _output_size()
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=w,
            output_height=h,
        )
        return png_path
    except Exception:
        cache_dir = settings.data_dir / "streams" / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "stock-bg-dark.png"
        if cache_path.exists():
            try:
                _normalize_to_16_9(cache_path)
            except Exception:
                pass
            return cache_path
        try:
            import cairosvg
            w, h = _output_size()
            cairosvg.svg2png(
                url=str(_stock_dark_svg_path()),
                write_to=str(cache_path),
                output_width=w,
                output_height=h,
            )
            try:
                _normalize_to_16_9(cache_path)
            except Exception:
                pass
            return cache_path
        except Exception:
            raise RuntimeError(
                "Could not render stock dark background. Place stock-background.png in app/static/ or ensure stock-background-dark.svg exists."
            ) from None


def default_overlay_placements() -> list[OverlayPlacement]:
    """Default positions for stock/stock-dark: layout with channel top-left, artist image left, bio right of image, song/artist below. Uses current output size (default 1280×720)."""
    w, h = _output_size()
    if w <= 0 or h <= 0:
        w, h = 1280, 720
    # Explicit layout for 1280×720 (default); scale proportionally for other sizes
    def sx(x: int, base_w: int = 1280) -> int:
        return int(round(x * w / base_w))
    def sy(y: int, base_h: int = 720) -> int:
        return int(round(y * h / base_h))
    def sf(s: int) -> int:
        return max(14, int(round(s * min(w, h) / 720)))
    # Base positions at 1280×720: channel top-left, image centered vs bio/track, bio right, song/artist right + double gap
    base = {
        "channel_name": (27, 27, 0, 0, 20),
        "song_title": (80, 520, 0, 0, 32),     # track title, down a little
        "artist_name": (80, 598, 0, 0, 28),    # artist name, a tad more space below track
        "artist_bio": (520, 270, 0, 0, 26),    # bio position (good)
        "artist_image": (160, 230, 200, 200, 0),  # moved up a bit more
    }
    return [
        OverlayPlacement(key="channel_name", x=sx(base["channel_name"][0]), y=sy(base["channel_name"][1]), width=0, height=0, font_size=sf(base["channel_name"][4]), anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="song_title", x=sx(base["song_title"][0]), y=sy(base["song_title"][1]), width=0, height=0, font_size=sf(base["song_title"][4]), anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="artist_name", x=sx(base["artist_name"][0]), y=sy(base["artist_name"][1]), width=0, height=0, font_size=sf(base["artist_name"][4]), anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="artist_bio", x=sx(base["artist_bio"][0]), y=sy(base["artist_bio"][1]), width=0, height=0, font_size=sf(base["artist_bio"][4]), anchor="nw", font_color="white", shadow_color="black", font_style="normal", scroll_speed=0),
        OverlayPlacement(key="artist_image", x=sx(base["artist_image"][0]), y=sy(base["artist_image"][1]), width=sx(base["artist_image"][2]), height=sy(base["artist_image"][3]), font_size=0, anchor="nw"),
    ]


def get_placement(placements: list[OverlayPlacement], key: str) -> OverlayPlacement | None:
    """Return placement for key, or None."""
    for p in placements:
        if p.key == key:
            return p
    return None
