"""Ensure repository-root ICON.ico is valid for PyInstaller + Pillow.

Some tools save a PNG with a ``.ico`` extension or prepend junk bytes. PyInstaller
uses Pillow to normalize icons; if Pillow cannot read the file, the build fails.

This script tries to load ``ICON.ico``; if that fails, it looks for a PNG stream
inside the file (IHDR chunk), rebuilds a minimal PNG, then writes a proper ICO.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ICON_PATH = ROOT / "ICON.ico"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _try_extract_png_from_bytes(raw: bytes) -> bytes | None:
    """Return PNG bytes if we can locate or reconstruct a PNG inside ``raw``."""
    if raw.startswith(PNG_MAGIC):
        return raw
    # Full magic present without leading 89 50?
    idx = raw.find(PNG_MAGIC)
    if idx >= 0:
        return raw[idx:]
    # Common corruption: missing first two bytes of magic; IHDR at known offset
    ihdr = raw.find(b"IHDR")
    if ihdr < 0:
        return None
    # IHDR must be chunk type at offset 4 within chunk; search for 13-byte IHDR chunk header
    chunk = raw.find(b"\x00\x00\x00\x0dIHDR", 0, min(len(raw), 200))
    if chunk >= 0:
        # Standard PNG: 8 byte magic + chunk (length + IHDR + data + crc)
        candidate = PNG_MAGIC + raw[chunk:]
        try:
            im = Image.open(io.BytesIO(candidate))
            im.load()
            return candidate
        except Exception:
            pass
    # Try prepending magic before first plausible chunk length + IHDR
    ihdr_len = raw.find(b"\x00\x00\x00\x0dIHDR")
    if ihdr_len >= 0:
        candidate = PNG_MAGIC + raw[ihdr_len:]
        try:
            im = Image.open(io.BytesIO(candidate))
            im.load()
            return candidate
        except Exception:
            pass
    return None


def main() -> int:
    if not ICON_PATH.is_file():
        print(f"Missing {ICON_PATH}", file=sys.stderr)
        return 1

    raw = ICON_PATH.read_bytes()

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        print(f"ICON.ico is already readable ({img.format}, {img.size[0]}×{img.size[1]}).")
        return 0
    except Exception:
        pass

    png_bytes = _try_extract_png_from_bytes(raw)
    if not png_bytes:
        print(
            "Could not parse ICON.ico as PNG/ICO. Replace it with a real .ico or .png file.",
            file=sys.stderr,
        )
        return 1

    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    # Single 256 layer — reliable with Pillow + PyInstaller
    r256 = img.resize((256, 256), Image.Resampling.LANCZOS)
    bak = ICON_PATH.with_suffix(".ico.bak")
    if not bak.exists():
        bak.write_bytes(raw)
        print(f"Backed up original to {bak.name}")
    r256.save(ICON_PATH, format="ICO")
    print(f"Wrote repaired {ICON_PATH} ({ICON_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
