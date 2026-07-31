"""Label OCR for map bands — Tesseract + KingShot label heuristics.

Pattern inspired by 4x-game-agent (PaddleOCR boxes → text+center), implemented
with pytesseract ``image_to_data`` so we stay dependency-light.
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from ks.cartograph.models import StructureHit
from ks.cartograph.project import round_tile, world_from_pixel
from ks.cartograph.viewport import tesseract_cmd

_CITY = re.compile(r"(\d{1,2})\s*\[([A-Za-z0-9]+)\]\s*(\S.+)")
_LEVEL = re.compile(r"(?:^|\b)(?:Lv\.?\s*)?(\d{1,2})(?:\b|\s*\[)", re.I)
_TRAP = re.compile(r"(Hunting\s+Trap|Bear\s+Trap)\s*\d*", re.I)
_BUILDING = re.compile(
    r"Alliance\s+(Woodmill|Mill|Iron\s+Mine|Quarry|Banner|HQ)|Plains\s+HQ",
    re.I,
)
_KEEP = re.compile(
    r"(\[\w+\].+)|(Hunting\s+Trap)|(Bear\s+Trap)|(Alliance\s+\w+)|(Plains\s+HQ)|(\d{1,2}\s*\[\w+\])",
    re.I,
)

DEFAULT_OCR_SCALE = 3.0
MIN_WORD_CONF = 35


def parse_level(label: str) -> int | None:
    """Extract a visible object level from OCR text when present."""
    if m := _CITY.search(label):
        return int(m.group(1))
    if m := _LEVEL.search(label):
        value = int(m.group(1))
        if 1 <= value <= 30:
            return value
    return None


def infer_kind(label: str) -> str | None:
    if re.search(r"Plains\s+HQ|Alliance\s+HQ", label, re.I):
        return "hq"
    if _TRAP.search(label):
        return "trap"
    if m := re.search(r"Alliance\s+(Woodmill|Mill|Iron\s+Mine|Quarry|Banner)", label, re.I):
        name = m.group(1).lower()
        if "banner" in name:
            return "banner"
        if "mine" in name or "quarry" in name:
            return "building"
        return "mill"
    if _CITY.search(label):
        return "city"
    return None


def preprocess_label_band(image: np.ndarray, *, scale: float = DEFAULT_OCR_SCALE) -> np.ndarray:
    """Return contrast-enhanced upscaled grayscale for OCR."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"image must be HxWx3; got {image.shape}")
    if scale < 1.0:
        raise ValueError(f"scale must be >= 1; got {scale}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    if scale != 1.0:
        enhanced = cv2.resize(
            enhanced,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
    return enhanced


def extract_labels_stub(_image: np.ndarray) -> list[tuple[str, float, float]]:
    return []


def extract_labels(image: np.ndarray) -> list[tuple[str, float, float]]:
    """OCR map band → list of (label, px, py) centers."""
    return [(label, px, py) for label, px, py, _conf in extract_labels_with_confidence(image)]


def extract_labels_with_confidence(
    image: np.ndarray,
    *,
    scale: float = DEFAULT_OCR_SCALE,
) -> list[tuple[str, float, float, float]]:
    """OCR map band → list of (label, px, py, confidence in (0, 1])."""
    try:
        import pytesseract
    except ImportError:
        return []

    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    up = preprocess_label_band(image, scale=scale)
    data = pytesseract.image_to_data(
        up,
        output_type=pytesseract.Output.DICT,
        config="--psm 11",
    )

    lines: dict[tuple[int, int, int], list[tuple[str, int, int, int, int, float]]] = {}
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        conf_raw = float(data["conf"][i])
        if not text or conf_raw < MIN_WORD_CONF:
            continue
        key = (
            int(data["block_num"][i]),
            int(data["par_num"][i]),
            int(data["line_num"][i]),
        )
        lines.setdefault(key, []).append(
            (
                text,
                int(data["left"][i]),
                int(data["top"][i]),
                int(data["width"][i]),
                int(data["height"][i]),
                conf_raw / 100.0,
            )
        )

    boxes: list[tuple[str, float, float, float]] = []
    for words in lines.values():
        label = " ".join(w[0] for w in words)
        if not _KEEP.search(label) and infer_kind(label) is None:
            continue
        xs0 = min(w[1] for w in words)
        ys0 = min(w[2] for w in words)
        xs1 = max(w[1] + w[3] for w in words)
        ys1 = max(w[2] + w[4] for w in words)
        cx = (xs0 + xs1) / 2.0 / scale
        cy = (ys0 + ys1) / 2.0 / scale
        conf = float(sum(w[5] for w in words) / len(words))
        conf = min(1.0, max(1e-3, conf))
        boxes.append((label, cx, cy, conf))
    return boxes


def hits_from_label_boxes(
    boxes: list[tuple[str, float, float]],
    *,
    viewport: tuple[float, float],
    crop_center: tuple[float, float],
    mat: np.ndarray,
    source: str = "",
) -> list[StructureHit]:
    out: list[StructureHit] = []
    for label, px, py in boxes:
        kind = infer_kind(label)
        if kind is None:
            continue
        wx, wy = world_from_pixel(
            px, py, viewport=viewport, crop_center=crop_center, mat=mat
        )
        tx, ty = round_tile(wx, wy)
        out.append(StructureHit.from_kind(label, kind, tx, ty, source=source))
    return out
