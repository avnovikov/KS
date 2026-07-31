"""Label OCR for map bands — Tesseract + KingShot label heuristics.

Pattern inspired by 4x-game-agent (PaddleOCR boxes → text+center), implemented
with pytesseract ``image_to_data`` so we stay dependency-light. EasyOCR is used
as a secondary pass when installed (better on soft alliance/city plates).
"""

from __future__ import annotations

import re
from functools import lru_cache

import cv2
import numpy as np

from ks.cartograph.models import StructureHit
from ks.cartograph.project import round_tile, world_from_pixel
from ks.cartograph.viewport import tesseract_cmd

# City: "30 [ROY]lord123" — tolerate OCR junk around brackets.
_CITY = re.compile(
    r"(\d{1,2})\s*[\[\(\{]+\s*([A-Za-z0-9]{2,8})\s*[\]\)\}]*\s*(\S.+)",
    re.I,
)
_CITY_LOOSE = re.compile(
    r"(\d{1,2}).{0,4}\[?\s*([A-Za-z]{2,6})\s*\]?\s*(lord\w*|Mayor\w*|[A-Za-z][\w.]{2,})",
    re.I,
)
_LEVEL = re.compile(r"(?:^|\b)(?:Lv\.?\s*)?(\d{1,2})(?:\b|\s*\[)", re.I)
_TRAP = re.compile(r"(Hunting\s+Trap|Bear\s+Trap)\s*\d*", re.I)
_ALLIANCE_FUZZY = re.compile(
    r"All[il1]ance\s+(Woo\w*|Mill|Ir[o0]n\s*M\w*|Quar\w*|Bann\w*|HQ)|Plains\s+HQ",
    re.I,
)
_KEEP = re.compile(
    r"(Hunting\s+Trap)|(Bear\s+Trap)|(All[il1]ance\s+\w+)|(Plains\s+HQ)"
    r"|(lord\w+)|(\d{1,2}\s*\[[A-Za-z]{2,6}\])",
    re.I,
)
_UI_NOISE = re.compile(
    r"([xy]\s*:)|(\d{1,2}:\d{2})|(^\s*[\d.\s:kKmM%]+\s*$)|(\bprs\b)|(\bdY\b)",
    re.I,
)

DEFAULT_OCR_SCALE = 3.0
MIN_WORD_CONF = 25  # lower: alliance/city nameplates are soft on the map


def _repair_city_tag(tag: str, name: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", tag.upper())
    blob = (letters + name).lower()
    if "lord" in name.lower() and (
        letters.startswith("OY") or letters in {"RO", "RY", "R", "OYJORD", "ROY", "OYOR", "OYJOR"}
    ):
        return "ROY"
    if "mono" in blob or "poly" in blob:
        return "ROY"
    if len(letters) >= 2:
        return letters[:6]
    return tag.upper()[:6]


def _repair_city_name(name: str) -> str:
    text = name.strip(" .,-|'\"")
    text = re.sub(r"^(jord|ord)", "lord", text, flags=re.I)
    text = re.sub(r"polyi", "poly", text, flags=re.I)
    text = re.sub(r"monopoly\s*123", "Monopoly123", text, flags=re.I)
    if m := re.search(r"lord\s*(\d{6,})", text, re.I):
        return f"lord{m.group(1)}"
    if m := re.search(r"(?:jord|ord)(\d{8,})", text, re.I):
        return f"lord{m.group(1)}"
    # Digits glued after broken tag text
    if m := re.search(r"(\d{9,})", text):
        if "lord" not in text.lower() and sum(c.isalpha() for c in text) <= 4:
            return f"lord{m.group(1)}"
    if re.search(r"mono|poly", text, re.I):
        return "Monopoly123"
    return text


def _plausible_city_parts(level: str, tag: str, name: str) -> bool:
    """Reject search-bar / HUD OCR that only looks like ``N [tag]text``."""
    try:
        lv = int(level)
    except ValueError:
        return False
    if not (1 <= lv <= 35):
        return False
    tag_u = tag.upper()
    letters = re.sub(r"[^A-Za-z]", "", tag_u)
    digits = re.sub(r"[^0-9]", "", tag_u)
    if len(letters) < 2:
        return False
    if len(digits) > len(letters):
        return False
    if re.fullmatch(r"\d+", tag_u):
        return False
    name_s = name.strip()
    if len(name_s) < 2:
        return False
    if _UI_NOISE.search(name_s):
        return False
    if name_s.lower() in {"alliance", "woodmill", "quarry", "banner", "mill"}:
        return False
    # OCR sometimes emits reversed/garbage alliance fragments as fake cities.
    compact = re.sub(r"[^a-z]", "", name_s.lower())
    if compact in {"nitolla", "ecnailla", "allianc"} or "alliance" in compact:
        return False
    if "lord" in name_s.lower():
        return True
    if sum(c.isalpha() for c in name_s) < 3:
        return False
    return True


def normalize_ocr_label(raw: str) -> str:
    """Clean common Tesseract misreads on KingShot nameplates."""
    text = " ".join((raw or "").split())
    text = text.replace("|", "I").replace("{", "[").replace("}", "]")
    text = re.sub(r"^\s*Ke\s+", "", text, flags=re.I)
    # Alliance / trap repairs before city bracket cleanup.
    text = re.sub(r"All[il1]ance", "Alliance", text, flags=re.I)
    text = re.sub(r"Alliance\s+Woo\w*", "Alliance Woodmill", text, flags=re.I)
    text = re.sub(r"Alliance\s+Wood\s*mill", "Alliance Woodmill", text, flags=re.I)
    text = re.sub(r"Alliance\s+Quar\w*", "Alliance Quarry", text, flags=re.I)
    text = re.sub(r"Alliance\s+Ir[o0]n\s*M\w*", "Alliance Iron Mine", text, flags=re.I)
    text = re.sub(r"Alliance\s+Bann\w*", "Alliance Banner", text, flags=re.I)
    text = re.sub(r"Alliance\s+HQ\b", "Alliance HQ", text, flags=re.I)
    text = re.sub(r"Plains\s+HQ", "Plains HQ", text, flags=re.I)
    text = re.sub(r"Hunt\w*\s+Trap", "Hunting Trap", text, flags=re.I)
    text = re.sub(r"Bear\s+Trap", "Bear Trap", text, flags=re.I)
    # Prefer alliance kind when both appear in one OCR blob.
    if m := re.search(
        r"(Alliance\s+(?:Woodmill|Quarry|Iron\s+Mine|Banner|HQ|Mill)|Plains\s+HQ)",
        text,
        re.I,
    ):
        alliance = m.group(1)
        if len(text) > len(alliance) + 3:
            text = alliance
    # City: prefer "N [TAG]name" when parts look like a real nameplate.
    if m := _CITY.search(text) or _CITY_LOOSE.search(text):
        level, tag, name = m.group(1), m.group(2), m.group(3)
        name = _repair_city_name(name)
        tag = _repair_city_tag(tag, name)
        if _plausible_city_parts(level, tag, name):
            return f"{level} [{tag}]{name}"
    return text.strip()


def parse_level(label: str) -> int | None:
    """Extract a visible object level from OCR text when present."""
    cleaned = normalize_ocr_label(label)
    if m := _CITY.search(cleaned):
        level, tag, name = m.group(1), m.group(2), m.group(3)
        if _plausible_city_parts(level, tag, name):
            return int(level)
    if m := _LEVEL.search(cleaned):
        value = int(m.group(1))
        if 1 <= value <= 30:
            return value
    return None


def infer_kind(label: str) -> str | None:
    cleaned = normalize_ocr_label(label)
    if re.search(r"Plains\s+HQ|Alliance\s+HQ", cleaned, re.I):
        return "hq"
    if _TRAP.search(cleaned):
        return "trap"
    if m := re.search(
        r"Alliance\s+(Woodmill|Mill|Iron\s+Mine|Quarry|Banner)", cleaned, re.I
    ):
        name = m.group(1).lower()
        if "banner" in name:
            return "banner"
        if "mine" in name or "quarry" in name:
            return "building"
        return "mill"
    if _ALLIANCE_FUZZY.search(label) or _ALLIANCE_FUZZY.search(cleaned):
        low = cleaned.lower()
        if "hq" in low:
            return "hq"
        if "banner" in low:
            return "banner"
        if "quarry" in low or "iron" in low:
            return "building"
        if "wood" in low or "mill" in low:
            return "mill"
    if m := _CITY.search(cleaned) or _CITY_LOOSE.search(cleaned):
        if _plausible_city_parts(m.group(1), m.group(2), _repair_city_name(m.group(3))):
            return "city"
    # Raw lord id without a clean level/tag still counts as a city nameplate.
    if re.search(r"\blord\d{6,}\b", cleaned, re.I):
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
    passes: list[tuple[str, float, float, float]] = []
    passes.extend(_extract_tesseract_boxes(image, scale=scale))
    passes.extend(_extract_easyocr_boxes(image))
    return _dedupe_label_boxes(passes)


def _extract_tesseract_boxes(
    image: np.ndarray, *, scale: float
) -> list[tuple[str, float, float, float]]:
    try:
        import pytesseract
    except ImportError:
        return []

    cmd = tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    up = preprocess_label_band(image, scale=scale)
    boxes: list[tuple[str, float, float, float]] = []
    for psm in ("11", "6"):
        data = pytesseract.image_to_data(
            up,
            output_type=pytesseract.Output.DICT,
            config=f"--psm {psm}",
        )
        boxes.extend(_boxes_from_tesseract_data(data, scale=scale))
    return boxes


@lru_cache(maxsize=1)
def _easyocr_reader():
    try:
        import easyocr
    except ImportError:
        return None
    try:
        return easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception:
        return None


def _extract_easyocr_boxes(image: np.ndarray) -> list[tuple[str, float, float, float]]:
    reader = _easyocr_reader()
    if reader is None:
        return []
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    try:
        results = reader.readtext(rgb, detail=1, paragraph=False)
    except Exception:
        return []

    boxes: list[tuple[str, float, float, float]] = []
    for box, text, conf in results:
        if float(conf) < 0.25:
            continue
        label = normalize_ocr_label(str(text))
        if infer_kind(label) is None and infer_kind(str(text)) is None:
            continue
        kind = infer_kind(label) or infer_kind(str(text))
        if kind is None:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        boxes.append(
            (
                normalize_ocr_label(label),
                (min(xs) + max(xs)) / 2.0,
                (min(ys) + max(ys)) / 2.0,
                float(min(1.0, max(1e-3, conf))),
            )
        )
    return boxes


def _boxes_from_tesseract_data(
    data: dict, *, scale: float
) -> list[tuple[str, float, float, float]]:
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
        raw = " ".join(w[0] for w in words)
        label = normalize_ocr_label(raw)
        if not _KEEP.search(raw) and not _KEEP.search(label) and infer_kind(label) is None:
            continue
        if infer_kind(label) is None and infer_kind(raw) is None:
            continue
        xs0 = min(w[1] for w in words)
        ys0 = min(w[2] for w in words)
        xs1 = max(w[1] + w[3] for w in words)
        ys1 = max(w[2] + w[4] for w in words)
        cx = (xs0 + xs1) / 2.0 / scale
        cy = (ys0 + ys1) / 2.0 / scale
        conf = float(sum(w[5] for w in words) / len(words))
        conf = min(1.0, max(1e-3, conf))
        kind = infer_kind(label) or infer_kind(raw)
        if kind is None:
            continue
        boxes.append((normalize_ocr_label(label), cx, cy, conf))
    return boxes


def _dedupe_label_boxes(
    boxes: list[tuple[str, float, float, float]],
    *,
    px_tol: float = 40.0,
) -> list[tuple[str, float, float, float]]:
    """Keep highest-confidence box per nearby duplicate label."""
    ranked = sorted(boxes, key=lambda b: b[3], reverse=True)
    kept: list[tuple[str, float, float, float]] = []
    for label, cx, cy, conf in ranked:
        clash = False
        for ol, ox, oy, _oc in kept:
            if abs(cx - ox) <= px_tol and abs(cy - oy) <= px_tol:
                same_kind = infer_kind(label) == infer_kind(ol)
                if label == ol or (same_kind and label[:12] == ol[:12]):
                    clash = True
                    break
        if not clash:
            kept.append((label, cx, cy, conf))
    return kept


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
        cleaned = normalize_ocr_label(label)
        kind = infer_kind(cleaned) or infer_kind(label)
        if kind is None:
            continue
        wx, wy = world_from_pixel(
            px, py, viewport=viewport, crop_center=crop_center, mat=mat
        )
        tx, ty = round_tile(wx, wy)
        out.append(StructureHit.from_kind(cleaned, kind, tx, ty, source=source))
    return out
