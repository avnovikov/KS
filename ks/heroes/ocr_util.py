"""Robust OCR helpers for stylized KingShot UI text."""

from __future__ import annotations

from typing import Callable, Iterable

import cv2
import numpy as np
import pytesseract

OcrFn = Callable[[np.ndarray, tuple[int, int, int, int]], str]


def crop_bgr_box(
    image: np.ndarray,
    box: tuple[int, int, int, int] | None,
    *,
    default: tuple[int, int, int, int] | None = None,
    none_returns_full: bool = False,
) -> np.ndarray:
    """Crop ``box=(x,y,w,h)`` from a BGR image with shared bounds checks.

    - ``box is None`` and ``none_returns_full`` → return ``image`` unchanged.
    - ``box is None`` and ``default`` set → use ``default``.
    - otherwise require an explicit box.
    """
    if image.ndim not in (2, 3):
        raise ValueError(f"image must be 2D or 3D; got shape {image.shape}")
    if box is None:
        if none_returns_full:
            return image
        if default is not None:
            box = default
        else:
            raise ValueError("box is required")
    x, y, w, h = box
    if w <= 0 or h <= 0:
        raise ValueError(f"box w/h must be > 0; got {box}")
    img_h, img_w = image.shape[:2]
    if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
        raise ValueError(f"box {box} outside image bounds")
    return image[y : y + h, x : x + w]


def region_text_lower(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    ocr_fn: OcrFn | None = None,
    psm: int = 6,
    whitelist: str | None = None,
) -> str:
    """OCR a region and return lowercased text."""
    if ocr_fn is not None:
        return ocr_fn(image, box).lower()
    return ocr_box_robust(image, box, psm=psm, whitelist=whitelist).lower()


def text_has_any(text: str, needles: Iterable[str]) -> bool:
    """True when any needle appears in ``text``."""
    return any(n in text for n in needles)


def ocr_box_robust(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    whitelist: str | None = None,
    psm: int = 7,
) -> str:
    """OCR a crop with upscale + Otsu variants; pick the longest non-empty result."""
    if image.ndim not in (2, 3):
        raise ValueError("image must be 2D or 3D")
    crop = crop_bgr_box(image, box)

    if crop.ndim == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = crop

    up = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    _, th = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants = (up, th, 255 - th)

    cfg = f"--psm {psm}"
    if whitelist:
        cfg = f"{cfg} -c tessedit_char_whitelist={whitelist}"

    texts: list[str] = []
    for variant in variants:
        text = pytesseract.image_to_string(variant, config=cfg).strip()
        if text:
            texts.append(text)
    if not texts:
        return ""
    return max(texts, key=len)
