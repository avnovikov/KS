"""Extract teal/green highlighted current skill bonus from a BGR panel crop."""

from __future__ import annotations

import re

import cv2
import numpy as np
import pytesseract

from ks.heroes.ocr_util import crop_bgr_box

_PERCENT_OR_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*%?")


def teal_highlight_mask(bgr: np.ndarray) -> np.ndarray:
    """Binary mask of teal/green UI highlight pixels (current skill tier)."""
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError(f"bgr must be HxWx3; got shape {bgr.shape}")
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hsv_mask = cv2.inRange(hsv, (40, 70, 90), (95, 255, 255))
    b, g, r = cv2.split(bgr)
    bgr_mask = (
        (g > 160)
        & (b > 80)
        & (r < 120)
        & ((g.astype(np.int16) - r.astype(np.int16)) > 50)
    ).astype(np.uint8) * 255
    return cv2.bitwise_or(hsv_mask, bgr_mask)


def _crop_to_box(
    image: np.ndarray, box: tuple[int, int, int, int] | None
) -> np.ndarray:
    return crop_bgr_box(image, box, none_returns_full=True)


def _denoise_teal_mask(mask: np.ndarray) -> np.ndarray:
    """Drop connected components too small/thin to be digit strokes."""
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    clean = np.zeros_like(mask)
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        height = int(stats[i, cv2.CC_STAT_HEIGHT])
        if 12 <= area <= 10_000 and height >= 5:
            clean[labels == i] = 255
    return clean


def _ocr_percent_candidates(mask: np.ndarray) -> list[float]:
    """Run OCR across polarity/PSM variants, collecting plausible percents."""
    up = cv2.resize(mask, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    candidates: list[float] = []
    for variant in (up, 255 - up):
        for psm in (7, 8, 6):
            text = pytesseract.image_to_string(
                variant,
                config=f"--psm {psm} -c tessedit_char_whitelist=0123456789.%",
            ).strip()
            if not text:
                continue
            for match in _PERCENT_OR_NUM.finditer(text.replace(",", ".")):
                value = float(match.group(1))
                if 1.0 <= value <= 400.0:
                    candidates.append(value)
    return candidates


def extract_teal_current_percent(
    image: np.ndarray,
    box: tuple[int, int, int, int] | None = None,
) -> float | None:
    """OCR the teal/green current bonus percent inside ``image`` or ``box``.

    Returns a float like ``216.0`` for ``216%``, or None if nothing reliable.
    """
    if image.ndim not in (2, 3):
        raise ValueError("image must be 2D or 3D")
    crop = _crop_to_box(image, box)

    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)

    mask = teal_highlight_mask(crop)
    clean = _denoise_teal_mask(mask)
    if clean.sum() == 0:
        return None
    clean = cv2.dilate(clean, np.ones((2, 2), np.uint8), iterations=1)

    candidates = _ocr_percent_candidates(clean)
    if not candidates:
        return None
    # Most common reading wins (OCR often repeats the same %).
    return max(set(candidates), key=candidates.count)
