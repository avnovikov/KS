"""Read map viewport center (search bar X/Y) from bear-trap screenshots.

Part of the future map-OCR pipeline (mask → crop → viewport → labels → world).
Broader lessons / module sketch: assets/reference/bear-trap/FINDINGS.md
("Lessons learned — future OCR module").
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import cv2
import numpy as np
import yaml

# Manual fallbacks when OCR fails or misparses digits.
FALLBACK_VIEWPORT: dict[str, tuple[int, int]] = {
    "shot-05.png": (691, 826),
    "shot-06.png": (687, 829),
    "shot-09.png": (697, 828),
    "batch2/b2-01.png": (707, 825),
}

# Expected range for this bear-trap screenshot set (state #2339).
X_RANGE = (685, 710)
Y_RANGE = (812, 840)


def tesseract_cmd() -> str | None:
    for candidate in (
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        shutil.which("tesseract"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _parse_coords(text: str) -> tuple[int, int] | None:
    m = re.search(r"X:\s*(\d+)\s*Y:\s*(\d+)", text, re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _in_range(x: int, y: int) -> bool:
    return X_RANGE[0] <= x <= X_RANGE[1] and Y_RANGE[0] <= y <= Y_RANGE[1]


def ocr_viewport_from_image(img: np.ndarray) -> tuple[tuple[int, int] | None, str]:
    """Return ((x, y)|None, raw OCR text) from a full screenshot."""
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("pytesseract not installed; run: pip install -e .") from exc

    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    h, w = img.shape[:2]
    crop = img[int(h * 0.835) : int(h * 0.885), int(w * 0.20) : int(w * 0.80)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

    for proc in (up, 255 - up):
        text = pytesseract.image_to_string(proc, config="--psm 6")
        coords = _parse_coords(text)
        if coords and _in_range(*coords):
            return coords, text.replace("\n", " ")
    text = pytesseract.image_to_string(up, config="--psm 6")
    return _parse_coords(text), text.replace("\n", " ")


def ocr_viewport(path: Path) -> tuple[tuple[int, int] | None, str]:
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    return ocr_viewport_from_image(img)


def rel_key(path: Path, shots_root: Path) -> str:
    if path.parent != shots_root and path.parent.name in ("batch2", "batch3"):
        return f"{path.parent.name}/{path.name}"
    return path.name


def resolve_viewport(key: str, ocr: tuple[int, int] | None) -> tuple[int, int, str]:
    if ocr and _in_range(*ocr):
        return ocr[0], ocr[1], "ocr"
    if key in FALLBACK_VIEWPORT:
        x, y = FALLBACK_VIEWPORT[key]
        return x, y, "fallback"
    if ocr:
        return ocr[0], ocr[1], "ocr-unvalidated"
    raise ValueError(f"no viewport for {key}; add FALLBACK_VIEWPORT entry")


def scan_shots(shots_dir: Path) -> dict[str, dict[str, int | str]]:
    paths = sorted(shots_dir.glob("shot-*.png")) + sorted((shots_dir / "batch2").glob("b2-*.png"))
    out: dict[str, dict[str, int | str]] = {}
    for path in paths:
        key = rel_key(path, shots_dir)
        ocr, _raw = ocr_viewport(path)
        x, y, source = resolve_viewport(key, ocr)
        out[key] = {"x": x, "y": y, "source": source}
    return out


def load_or_scan_viewport_yaml(shots_dir: Path, yaml_path: Path) -> dict[str, tuple[int, int]]:
    if yaml_path.exists():
        data = yaml.safe_load(yaml_path.read_text()) or {}
        viewport = data.get("viewport", {})
        if len(viewport) >= 16:
            return {k: (v["x"], v["y"]) for k, v in viewport.items()}

    scanned = scan_shots(shots_dir)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml.safe_dump({"viewport": scanned}, yaml_path.open("w"), sort_keys=True)
    return {k: (v["x"], v["y"]) for k, v in scanned.items()}
