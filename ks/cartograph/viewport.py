"""Multi-resolution viewport OCR (search bar #STATE X:… Y:…)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import cv2
import numpy as np

# Fraction bands to try (y0,y1,x0,x1) — phone portrait + BlueStacks layouts.
# Search bar sits just above chat on 1080×1920; 0.78–0.86 was too short.
# Tile / building info banners put X:Y in the mid screen card.
_VIEWPORT_BANDS: tuple[tuple[float, float, float, float], ...] = (
    (0.78, 0.88, 0.05, 0.95),  # BlueStacks 1080x1920 search bar
    (0.76, 0.86, 0.05, 0.95),
    (0.835, 0.885, 0.20, 0.80),  # older phone exports
    (0.88, 0.94, 0.15, 0.85),
    (0.72, 0.80, 0.15, 0.85),
    (0.12, 0.32, 0.10, 0.90),  # upper lord/city popup fallback
    (0.15, 0.42, 0.08, 0.92),
    (0.35, 0.58, 0.12, 0.88),  # tile/building info popup fallback
    (0.30, 0.65, 0.10, 0.90),
)

_COORD_RE = re.compile(
    r"#?\s*(\d{3,5})?\s*X\s*[:：]?\s*(\d{1,5})\s*Y\s*[:：]?\s*(\d{1,5})",
    re.I,
)
_SEARCH_BAR_BAND = (0.78, 0.88, 0.05, 0.95)


def tesseract_cmd() -> str | None:
    for candidate in (
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        shutil.which("tesseract"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def parse_viewport_text(text: str) -> tuple[int, int] | None:
    m = _COORD_RE.search(text.replace("\n", " "))
    if not m:
        return None
    return int(m.group(2)), int(m.group(3))


def ocr_search_bar_from_image(img: np.ndarray) -> tuple[tuple[int, int] | None, str]:
    """Read only the persistent bottom coordinate bar with a small OCR budget."""
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("pytesseract not installed; run: pip install -e .") from exc

    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    h, w = img.shape[:2]
    y0, y1, x0, x1 = _SEARCH_BAR_BAND
    crop = img[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]
    if crop.size == 0:
        return None, ""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    best_text = ""
    for proc in (gray, up, 255 - up):
        for psm in ("6", "7", "11"):
            text = pytesseract.image_to_string(proc, config=f"--psm {psm}")
            best_text = text.replace("\n", " ").strip()
            coords = parse_viewport_text(text)
            if coords is None:
                continue
            if 100 <= coords[0] <= 5000 and 10 <= coords[1] <= 5000:
                return coords, best_text
    return None, best_text


def ocr_viewport_from_image(
    img: np.ndarray,
    *,
    require_range: tuple[tuple[int, int], tuple[int, int]] | None = None,
) -> tuple[tuple[int, int] | None, str]:
    """Return ((x, y)|None, raw OCR text) from a full screenshot."""
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("pytesseract not installed; run: pip install -e .") from exc

    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    h, w = img.shape[:2]
    best_text = ""
    for y0, y1, x0, x1 in _VIEWPORT_BANDS:
        crop = img[int(h * y0) : int(h * y1), int(w * x0) : int(w * x1)]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        up = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        # Native gray often beats 3× upscale on BlueStacks search bar.
        variants = (gray, up, 255 - up)
        for proc in variants:
            for psm in ("6", "7", "11"):
                text = pytesseract.image_to_string(proc, config=f"--psm {psm}")
                coords = parse_viewport_text(text)
                if coords is None:
                    continue
                # Prefer 3–4 digit map coords (reject 1–2 digit kingdom bleed like X:16)
                # and reject OCR glitches like X:10560.
                if coords[0] < 100 or coords[0] > 5000:
                    continue
                if coords[1] < 10 or coords[1] > 5000:
                    continue
                best_text = text.replace("\n", " ").strip()
                if require_range is None:
                    return coords, best_text
                (xmin, xmax), (ymin, ymax) = require_range
                x, y = coords
                if xmin <= x <= xmax and ymin <= y <= ymax:
                    return coords, best_text
    return None, best_text
