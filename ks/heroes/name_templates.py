"""Labeled name-crop templates for hero title matching.

After ``capture-names``, each ``names/<Hero>.png`` is a ground-truth crop.
Matching prefers OpenCV template correlation against those crops, then falls
back to Tesseract + catalog fuzzy match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ks.heroes.name_ocr import (
    _bright_name_mask,
    match_known_hero_name,
    ocr_top_center_name,
)
from ks.heroes.name_shot import sanitize_name_filename


@dataclass(frozen=True)
class NameTemplate:
    name: str
    path: Path
    mask: np.ndarray  # uint8 binary template (letterform)


def load_name_templates(names_dir: Path) -> list[NameTemplate]:
    """Load ``*.png`` crops (except example_*) as labeled name templates."""
    if not isinstance(names_dir, Path):
        raise TypeError(f"names_dir must be Path; got {type(names_dir).__name__}")
    if not names_dir.is_dir():
        return []
    templates: list[NameTemplate] = []
    for path in sorted(names_dir.glob("*.png")):
        stem = path.stem
        if stem.startswith(
            ("example_", "show_", "cmp_", "top", "probe_", "live_")
        ) or stem.endswith("_debug"):
            continue
        img = cv2.imread(str(path))
        if img is None:
            continue
        mask = _bright_name_mask(img)
        if int(mask.sum() // 255) < 40:
            continue
        templates.append(NameTemplate(name=stem, path=path, mask=mask))
    return templates


def _resize_mask_height(mask: np.ndarray, *, target_h: int = 64) -> np.ndarray:
    scale = target_h / max(1, mask.shape[0])
    return cv2.resize(
        mask,
        (max(8, int(mask.shape[1] * scale)), target_h),
        interpolation=cv2.INTER_NEAREST,
    )


def _pad_masks_equal_width(
    probe: np.ndarray, template: np.ndarray, *, target_h: int
) -> tuple[np.ndarray, np.ndarray]:
    width = max(probe.shape[1], template.shape[1])
    probe_p = np.zeros((target_h, width), dtype=np.uint8)
    tmpl_p = np.zeros((target_h, width), dtype=np.uint8)
    ox = (width - probe.shape[1]) // 2
    tx = (width - template.shape[1]) // 2
    probe_p[:, ox : ox + probe.shape[1]] = probe
    tmpl_p[:, tx : tx + template.shape[1]] = template
    return probe_p, tmpl_p


def _mask_correlation(a_mask: np.ndarray, b_mask: np.ndarray) -> float | None:
    a = a_mask.astype(np.float32) / 255.0
    b = b_mask.astype(np.float32) / 255.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return None
    return float(np.tensordot(a, b) / denom)


def _best_template_match(
    probe_r: np.ndarray, templates: list[NameTemplate], *, target_h: int
) -> tuple[str | None, float, float]:
    best_name: str | None = None
    best_score = -1.0
    second = -1.0
    for tmpl in templates:
        t_r = _resize_mask_height(tmpl.mask, target_h=target_h)
        probe_p, t_p = _pad_masks_equal_width(probe_r, t_r, target_h=target_h)
        score = _mask_correlation(probe_p, t_p)
        if score is None:
            continue
        if score > best_score:
            second = best_score
            best_score = score
            best_name = tmpl.name
        elif score > second:
            second = score
    return best_name, best_score, second


def match_name_template(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    templates: list[NameTemplate],
    *,
    cutoff: float = 0.55,
) -> tuple[str | None, float]:
    """Return (hero_name, score) via normalized correlation on bright letter masks."""
    if not templates:
        return None, 0.0
    if image.ndim != 3:
        raise ValueError("image must be BGR")
    x, y, w, h = box
    crop = image[y : y + h, x : x + w]
    if crop.size == 0:
        return None, 0.0
    target_h = 64
    probe_r = _resize_mask_height(_bright_name_mask(crop), target_h=target_h)
    best_name, best_score, second = _best_template_match(
        probe_r, templates, target_h=target_h
    )
    if best_name is None or best_score < cutoff:
        return None, best_score
    if best_score - second < 0.04 and best_score < 0.75:
        return None, best_score
    return best_name, best_score


def train_name_ocr_from_crops(
    names_dir: Path,
    *,
    labels: dict[str, str] | None = None,
) -> dict:
    """Evaluate Tesseract + template self-match on labeled name crops.

    ``labels`` maps filename stem → display name (default: stem is the name).
    Writes ``names_dir/ocr_train_report.json``.
    """
    if not names_dir.is_dir():
        raise FileNotFoundError(f"names_dir not found: {names_dir}")

    templates = load_name_templates(names_dir)
    report = {
        "names_dir": str(names_dir),
        "template_count": len(templates),
        "crops": [],
        "ocr_exact": 0,
        "ocr_fuzzy": 0,
        "template_self": 0,
        "total": 0,
    }

    for path in sorted(names_dir.glob("*.png")):
        stem = path.stem
        if stem.startswith(("example_", "show_", "cmp_", "top", "probe_", "live_")) or stem.endswith(
            "_debug"
        ):
            continue
        expected = (labels or {}).get(stem, stem)
        img = cv2.imread(str(path))
        if img is None:
            continue
        # Crop is already the name box — OCR with box = full image.
        h, w = img.shape[:2]
        # Rebuild a padded full-screen-like canvas so ocr_top_center_name box works,
        # or call mask OCR directly on the crop.
        raw = ocr_top_center_name(
            # Place crop at configured origin inside a blank canvas.
            _paste_at(img, x=300, y=26, canvas_size=(1920, 1080)),
            (300, 26, w, h),
        )
        fuzzy = match_known_hero_name(raw, [expected, *[t.name for t in templates]])
        # Self-template: match crop against all templates
        canvas = _paste_at(img, x=300, y=26, canvas_size=(1920, 1080))
        tmpl_name, tmpl_score = match_name_template(
            canvas, (300, 26, w, h), templates, cutoff=0.4
        )

        entry = {
            "file": path.name,
            "expected": expected,
            "ocr_raw": raw,
            "ocr_fuzzy": fuzzy,
            "template": tmpl_name,
            "template_score": round(tmpl_score, 4),
        }
        report["crops"].append(entry)
        report["total"] += 1
        if clean_eq(raw, expected):
            report["ocr_exact"] += 1
        if fuzzy == expected:
            report["ocr_fuzzy"] += 1
        if tmpl_name == expected:
            report["template_self"] += 1

    out = names_dir / "ocr_train_report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def clean_eq(raw: str, expected: str) -> bool:
    a = "".join(ch for ch in raw.lower() if ch.isalpha())
    b = "".join(ch for ch in expected.lower() if ch.isalpha())
    return bool(a) and a == b


def _paste_at(
    crop: np.ndarray,
    *,
    x: int,
    y: int,
    canvas_size: tuple[int, int],
) -> np.ndarray:
    """Paste a name crop onto a blank BGR canvas at (x, y). canvas_size=(H,W)."""
    h, w = canvas_size
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[:] = (120, 100, 60)  # teal-ish
    ch, cw = crop.shape[:2]
    x2 = min(w, x + cw)
    y2 = min(h, y + ch)
    canvas[y:y2, x:x2] = crop[0 : y2 - y, 0 : x2 - x]
    return canvas


def ensure_template_name_matches_file(names_dir: Path, hero_name: str) -> Path:
    """Return path for ``names/<Hero>.png`` using sanitize rules."""
    stem = sanitize_name_filename(hero_name)
    return names_dir / f"{stem}.png"
