#!/usr/bin/env python3
"""Clean up the muzic channelz logo: make background transparent, smooth jagged edges on 'channelz' text."""
from pathlib import Path
import sys

def main():
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        print("PIL/Pillow required: pip install Pillow")
        sys.exit(1)
    src = Path(__file__).resolve().parent.parent / "frontend" / "public" / "logo_source.png"
    out = Path(__file__).resolve().parent.parent / "frontend" / "public" / "logo.png"
    if not src.exists():
        print(f"Source not found: {src}")
        sys.exit(1)
    img = Image.open(src).convert("RGBA")
    data = img.getdata()
    new_data = []
    for i, (r, g, b, a) in enumerate(data):
        if r < 70 and g < 70 and b < 70:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, a))
    img.putdata(new_data)
    r, g, b, a = img.split()
    a_smooth = a.filter(ImageFilter.GaussianBlur(radius=0.8))
    a_data = list(a_smooth.getdata())
    a_new = [255 if x > 120 else (x * 2 if x > 40 else 0) for x in a_data]
    a_smooth.putdata(a_new)
    img = Image.merge("RGBA", (r, g, b, a_smooth))
    img.save(out, "PNG")
    print(f"Saved: {out}")
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "logo.png"
    if dist.parent.exists():
        import shutil
        shutil.copy2(out, dist)
        print(f"Copied to: {dist}")

if __name__ == "__main__":
    main()
