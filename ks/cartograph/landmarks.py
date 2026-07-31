"""Player / alliance name landmarks for mosaic alignment.

Names are nearly stable across overlapping screenshots; matching the same
label in two frames gives a hard pixel offset between those frames — more
reliable than a global overlap-scaled lattice for filling middle gaps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from ks.cartograph.labels import extract_labels

_LORD = re.compile(r"lord\s*(\d{4,})", re.I)
_UNIQUE_STRUCTURE = re.compile(
    r"(my\s*city|plains\s*hq|hunting\s*trap|bear\s*trap|alliance\s*hq|alliance\s*banner)",
    re.I,
)
# Alliance mills/quarries look identical across the map — do not use as pair anchors.
_AMBIGUOUS = re.compile(r"alliance\s*(woodmill|mill|iron\s*mine|quarry)", re.I)
_KEEP_RAW = re.compile(
    r"lord|my\s*city|plains\s*hq|hunting\s*trap|bear\s*trap|alliance\s*hq|alliance\s*banner|\[\w+\]",
    re.I,
)


@dataclass(frozen=True)
class NameLandmark:
    """A readable map label and its pixel center in a masked band."""

    name: str
    x: float
    y: float
    conf: float = 1.0


def is_registration_landmark_name(name: str) -> bool:
    """Return whether a normalized name is safe for cross-frame registration."""
    return bool(name) and not name.startswith("ambig:")


def normalize_landmark_name(text: str) -> str | None:
    """Collapse OCR variants into a stable landmark key.

    Player ``lord…`` ids are preferred anchors (nearly unique). Ambiguous
    repeated buildings (Woodmill / Quarry) are OCR'd for display but excluded
    from cross-frame pairing via :func:`landmark_pair_offsets`.
    """
    raw = (text or "").strip()
    if len(raw) < 3:
        return None
    compact = re.sub(r"\s+", "", raw)
    if m := _LORD.search(compact) or _LORD.search(raw):
        return f"lord{m.group(1)}"
    if m := (_AMBIGUOUS.search(raw) or _AMBIGUOUS.search(compact)):
        kind = re.sub(r"\s+", "", m.group(0).lower())
        return f"ambig:{kind}"
    if m := _UNIQUE_STRUCTURE.search(raw) or _UNIQUE_STRUCTURE.search(compact):
        return re.sub(r"\s+", "", m.group(0).lower())
    if _KEEP_RAW.search(raw):
        return compact.lower()
    return None


def extract_name_landmarks(band: np.ndarray) -> list[NameLandmark]:
    """OCR name-like labels on a masked map band."""
    if band.ndim != 3 or band.shape[0] < 32 or band.shape[1] < 32:
        raise ValueError(f"band must be HxWx3 with useful size; got {band.shape}")

    hits = _extract_easyocr(band)
    if not hits:
        hits = _extract_tesseract_labels(band)
    return _dedupe_landmarks(hits)


def _extract_tesseract_labels(band: np.ndarray) -> list[NameLandmark]:
    out: list[NameLandmark] = []
    for label, x, y in extract_labels(band):
        key = normalize_landmark_name(label)
        if key is None:
            continue
        out.append(NameLandmark(name=key, x=float(x), y=float(y), conf=0.7))
    return out


def _extract_easyocr(band: np.ndarray) -> list[NameLandmark]:
    try:
        import easyocr  # noqa: F401
    except ImportError:
        return []

    reader = _easyocr_reader()
    if reader is None:
        return []

    rgb = cv2.cvtColor(band, cv2.COLOR_BGR2RGB)
    try:
        results = reader.readtext(rgb, detail=1, paragraph=False)
    except Exception:
        return []

    out: list[NameLandmark] = []
    for box, text, conf in results:
        if float(conf) < 0.25:
            continue
        key = normalize_landmark_name(str(text))
        if key is None:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        out.append(
            NameLandmark(
                name=key,
                x=(min(xs) + max(xs)) / 2.0,
                y=(min(ys) + max(ys)) / 2.0,
                conf=float(conf),
            )
        )
    return out


_READER = None
_READER_FAILED = False


def _easyocr_reader():
    global _READER, _READER_FAILED
    if _READER_FAILED:
        return None
    if _READER is not None:
        return _READER
    try:
        import ssl

        import easyocr

        ssl._create_default_https_context = ssl._create_unverified_context
        _READER = easyocr.Reader(["en"], gpu=False, verbose=False)
        return _READER
    except Exception:
        _READER_FAILED = True
        return None


def _dedupe_landmarks(hits: list[NameLandmark]) -> list[NameLandmark]:
    """Keep highest-confidence hit per name (one city label per frame)."""
    best: dict[str, NameLandmark] = {}
    for h in hits:
        prev = best.get(h.name)
        if prev is None or h.conf > prev.conf:
            best[h.name] = h
    return list(best.values())


def landmark_pair_offsets(
    landmarks_by_cell: dict[tuple[int, int], list[NameLandmark]],
) -> list[tuple[tuple[int, int], tuple[int, int], float, float, float]]:
    """Constraints ``O_b - O_a = (dx, dy)`` from shared landmark names.

    Same label in frames A and B means the band origins differ by the
    difference of the label's local pixel positions. Skips ``ambig:`` keys
    (identical alliance mills) which falsely glue distant frames.
    """
    by_name: dict[str, list[tuple[tuple[int, int], NameLandmark]]] = {}
    for cell, lms in landmarks_by_cell.items():
        for lm in lms:
            if not is_registration_landmark_name(lm.name):
                continue
            by_name.setdefault(lm.name, []).append((cell, lm))

    out: list[tuple[tuple[int, int], tuple[int, int], float, float, float]] = []
    for occs in by_name.values():
        if len(occs) < 2:
            continue
        for i, (ca, la) in enumerate(occs):
            for cb, lb in occs[i + 1 :]:
                if ca == cb:
                    continue
                dx = float(la.x - lb.x)
                dy = float(la.y - lb.y)
                weight = 40.0 * min(la.conf, lb.conf)
                out.append((ca, cb, dx, dy, weight))
    return out
