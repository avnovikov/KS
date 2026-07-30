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
_TRAP = re.compile(r"(Hunting\s+Trap|Bear\s+Trap)\s*\d*", re.I)
_BUILDING = re.compile(
    r"Alliance\s+(Woodmill|Mill|Iron\s+Mine|Quarry|Banner|HQ)|Plains\s+HQ",
    re.I,
)
_KEEP = re.compile(
    r"(\[\w+\].+)|(Hunting\s+Trap)|(Bear\s+Trap)|(Alliance\s+\w+)|(Plains\s+HQ)|(\d{1,2}\s*\[\w+\])",
    re.I,
)


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


def extract_labels_stub(_image: np.ndarray) -> list[tuple[str, float, float]]:
    return []


def extract_labels(image: np.ndarray) -> list[tuple[str, float, float]]:
    """OCR map band → list of (label, px, py) centers."""
    try:
        import pytesseract
    except ImportError:
        return extract_labels_stub(image)

    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(up, output_type=pytesseract.Output.DICT, config="--psm 11")

    # Group words into lines by block/par/line ids.
    lines: dict[tuple[int, int, int], list[tuple[str, int, int, int, int]]] = {}
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text or int(data["conf"][i]) < 40:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        lines.setdefault(key, []).append(
            (
                text,
                int(data["left"][i]),
                int(data["top"][i]),
                int(data["width"][i]),
                int(data["height"][i]),
            )
        )

    boxes: list[tuple[str, float, float]] = []
    scale = 2.0
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
        boxes.append((label, cx, cy))
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
