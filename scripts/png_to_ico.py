"""Regenerate resources/ModelDocker.ico from resources/ModelDocker.png.

Run from the repository root:
    pip install pillow
    python scripts/png_to_ico.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PNG = ROOT / "resources" / "ModelDocker.png"
ICO = ROOT / "resources" / "ModelDocker.ico"


def main() -> None:
    if not PNG.is_file():
        raise SystemExit(f"Missing {PNG}")
    img = Image.open(PNG).convert("RGBA")
    ICO.parent.mkdir(parents=True, exist_ok=True)
    # Single embedded 256×256 layer — Pillow's multi-size ICO append_images produces
    # tiny broken files on some versions; Windows shells accept a solid 256 ICO.
    r256 = img.resize((256, 256), Image.Resampling.LANCZOS)
    r256.save(ICO, format="ICO")
    print(f"Wrote {ICO} ({ICO.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
