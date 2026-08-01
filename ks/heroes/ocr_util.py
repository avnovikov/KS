"""Robust OCR helpers for stylized KingShot UI text."""

from __future__ import annotations

import cv2
import numpy as np
import pytesseract


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
    x, y, w, h = box
    if w <= 0 or h <= 0:
        raise ValueError(f"box w/h must be > 0; got {box}")
    img_h, img_w = image.shape[:2]
    if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
        raise ValueError(f"box {box} outside image bounds")

    crop = image[y : y + h, x : x + w]
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
