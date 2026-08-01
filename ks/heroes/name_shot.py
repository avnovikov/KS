"""Save / rename top-center hero name crops next to scraped records."""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from ks.heroes.config import OcrBox


def sanitize_name_filename(name: str) -> str:
    """Turn a hero name into a safe PNG stem."""
    if not name or not str(name).strip():
        raise ValueError("name must be non-empty for screenshot filename")
    safe = re.sub(r"[^\w.\-]+", "_", str(name).strip(), flags=re.UNICODE)
    safe = safe.strip("._") or "unnamed"
    return safe


def crop_name_region(image: np.ndarray, box: OcrBox) -> np.ndarray:
    """Crop the configured top-center name box from a BGR screenshot."""
    h, w = image.shape[:2]
    x, y, bw, bh = box.x, box.y, box.w, box.h
    if x < 0 or y < 0 or bw <= 0 or bh <= 0:
        raise ValueError(f"invalid name box: x={x} y={y} w={bw} h={bh}")
    x2 = min(w, x + bw)
    y2 = min(h, y + bh)
    if x >= w or y >= h or x2 <= x or y2 <= y:
        raise ValueError(
            f"name box out of image bounds: box=({x},{y},{bw},{bh}) image=({w}x{h})"
        )
    return image[y:y2, x:x2].copy()


def save_name_screenshot(
    image: np.ndarray,
    box: OcrBox,
    names_dir: Path,
    hero_name: str,
) -> str:
    """Write ``names/<HeroName>.png`` and return the relative path string."""
    if not isinstance(names_dir, Path):
        raise TypeError(f"names_dir must be Path; got {type(names_dir).__name__}")
    names_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize_name_filename(hero_name)
    path = names_dir / f"{stem}.png"
    crop = crop_name_region(image, box)
    ok = cv2.imwrite(str(path), crop)
    if not ok:
        raise OSError(f"failed to write name screenshot: {path}")
    return f"names/{stem}.png"


def rename_name_screenshot(
    out_dir: Path,
    old_rel: str | None,
    new_name: str,
) -> str | None:
    """Rename an existing name crop to match ``new_name``; return new relative path."""
    if not old_rel:
        return None
    old_path = out_dir / old_rel
    stem = sanitize_name_filename(new_name)
    new_rel = f"names/{stem}.png"
    new_path = out_dir / new_rel
    if old_path.resolve() == new_path.resolve():
        return new_rel
    new_path.parent.mkdir(parents=True, exist_ok=True)
    if old_path.is_file():
        if new_path.is_file() and new_path.resolve() != old_path.resolve():
            new_path.unlink()
        old_path.rename(new_path)
        return new_rel
    return old_rel if (out_dir / old_rel).is_file() else new_rel
