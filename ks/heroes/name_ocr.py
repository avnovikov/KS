"""Top-center hero name OCR + fuzzy match against the hero catalog.

Single source of truth for static hero identity:
  ``config/hero_catalog.yaml`` (names, troop, rarity, widgets, arena hints).

Optional enricher (when populated):
  ``artifacts/heroes/catalog_cache/kingshotpro_heroes.json``
"""

from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.types import CatalogEntry
from ks.heroes.parse import clean_name, parse_rarity

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRO_CACHE = (
    _PROJECT_ROOT / "artifacts" / "heroes" / "catalog_cache" / "kingshotpro_heroes.json"
)
DEFAULT_CATALOG_YAML = _PROJECT_ROOT / "config" / "hero_catalog.yaml"

# UI rarity badge → catalog rarity string / roster card color
_UI_TO_CATALOG_RARITY = {
    "SSR": "legendary",
    "UR": "legendary",
    "SR": "epic",
    "R": "rare",
}
_RARITY_TO_COLOR = {
    "legendary": "orange",
    "epic": "purple",
    "rare": "blue",
}
_NAME_OCR_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz- &"


@lru_cache(maxsize=2)
def load_name_catalog(
    pro_path: str | None = None,
    yaml_path: str | None = None,
) -> dict[str, CatalogEntry]:
    """Load the hybrid catalog used for recommend + name matching."""
    pro = Path(pro_path) if pro_path else DEFAULT_PRO_CACHE
    yml = Path(yaml_path) if yaml_path else DEFAULT_CATALOG_YAML
    if not pro.is_file():
        # YAML-only still works (load_catalog tolerates empty pro list).
        pro.parent.mkdir(parents=True, exist_ok=True)
        if not pro.is_file():
            pro.write_text('{"heroes": []}\n', encoding="utf-8")
    return load_catalog(pro, yml)


def load_known_hero_names(
    pro_path: str | None = None,
    yaml_path: str | None = None,
) -> tuple[str, ...]:
    catalog = load_name_catalog(pro_path, yaml_path)
    return tuple(sorted(catalog.keys()))


def _normalize_rarity_filter(rarity: str | None, color: str | None) -> str | None:
    """Catalog rarity key from a UI rarity hint, or from card color as a fallback."""
    if rarity:
        return _UI_TO_CATALOG_RARITY.get(rarity.upper(), rarity.lower())
    color_norm = color.lower() if color else None
    if color_norm:
        # Map color → rarity when OCR missed SSR/SR/R.
        for rar, col in _RARITY_TO_COLOR.items():
            if col == color_norm:
                return rar
    return None


def _normalize_troop_filter(troop: str | None) -> str | None:
    troop_norm = troop.lower() if troop else None
    if troop_norm in {"archers", "bow"}:
        return "archer"
    if troop_norm in {"inf", "shield"}:
        return "infantry"
    if troop_norm in {"cav", "horse"}:
        return "cavalry"
    return troop_norm


def names_for_filters(
    catalog: dict[str, CatalogEntry],
    *,
    rarity: str | None = None,
    troop: str | None = None,
    color: str | None = None,
) -> tuple[str, ...]:
    """Subset catalog names by rarity / troop / card color."""
    rarity_norm = _normalize_rarity_filter(rarity, color)
    troop_norm = _normalize_troop_filter(troop)

    names = [
        name
        for name, entry in catalog.items()
        if (not rarity_norm or (entry.rarity or "").lower() == rarity_norm)
        and (not troop_norm or (entry.troop or "").lower() == troop_norm)
    ]
    return tuple(sorted(names))


def detect_rarity_color(
    image: np.ndarray,
    box: tuple[int, int, int, int] = (20, 90, 200, 120),
) -> str | None:
    """Guess rarity color from the top-left badge (orange/purple/blue)."""
    if image.ndim != 3:
        raise ValueError("image must be BGR")
    x, y, w, h = box
    crop = image[y : y + h, x : x + w]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    bands = {
        # Gold SSR letters + orange legendary frames
        "orange": cv2.bitwise_or(
            cv2.inRange(hsv, (8, 80, 100), (35, 255, 255)),
            cv2.inRange(hsv, (18, 40, 150), (40, 255, 255)),  # pale gold
        ),
        "purple": cv2.inRange(hsv, (125, 50, 50), (165, 255, 255)),
        "blue": cv2.inRange(hsv, (95, 80, 80), (118, 255, 255)),
    }
    scores = {k: int(m.sum() // 255) for k, m in bands.items()}
    best = max(scores, key=scores.get)
    second = sorted(scores.values(), reverse=True)[1]
    # Require a decisive winner — UI chrome is often bluish.
    if scores[best] < 150 or scores[best] < second * 1.4:
        return None
    return best


def detect_troop_hint(image: np.ndarray) -> str | None:
    """Best-effort troop from OCR near the class icons under the name."""
    h, w = image.shape[:2]
    band = image[150:250, max(0, w // 2 - 200) : min(w, w // 2 + 200)]
    text = pytesseract.image_to_string(band, config="--psm 6").lower()
    if "caval" in text or "horse" in text:
        return "cavalry"
    if "arch" in text or "bow" in text:
        return "archer"
    if "infan" in text or "shield" in text:
        return "infantry"
    # Expedition labels appear later; also peek raw for common typos.
    return None


def _bright_name_mask(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    whiteish = cv2.inRange(hsv, (0, 0, 160), (180, 80, 255))
    return cv2.bitwise_or(th, whiteish)


def _crop_name_box(
    image: np.ndarray, box: tuple[int, int, int, int] | None
) -> np.ndarray:
    h, w = image.shape[:2]
    if box is None:
        box = (300, 26, 480, 64)
    x, y, bw, bh = box
    if bw <= 0 or bh <= 0:
        raise ValueError(f"invalid box {box}")
    if x < 0 or y < 0 or x + bw > w or y + bh > h:
        raise ValueError(f"box {box} outside image")
    return image[y : y + bh, x : x + bw]


def _upscaled_name_variants(crop: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bright-text mask (both polarities) plus a plain upscaled grayscale crop."""
    mask = _bright_name_mask(crop)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    up_mask = cv2.resize(mask, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_NEAREST)
    up_gray = cv2.resize(
        cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY),
        None,
        fx=3.0,
        fy=3.0,
        interpolation=cv2.INTER_CUBIC,
    )
    return up_mask, 255 - up_mask, up_gray


def _name_ocr_candidates(variants: tuple[np.ndarray, ...]) -> list[str]:
    candidates: list[str] = []
    for im in variants:
        for psm in (7, 8, 13):
            text = pytesseract.image_to_string(im, config=f"--psm {psm}").strip()
            if text:
                candidates.append(text)
            wl = pytesseract.image_to_string(
                im,
                config=f"--psm {psm} -c tessedit_char_whitelist={_NAME_OCR_WHITELIST}",
            ).strip()
            if wl:
                candidates.append(wl)
    return candidates


def _best_name_candidate(candidates: list[str]) -> str:
    """Prefer more letters, then fewer words, then longer text."""
    if not candidates:
        return ""
    return max(
        candidates,
        key=lambda t: (sum(ch.isalpha() for ch in t), -len(t.split()), len(t)),
    )


def ocr_top_center_name(
    image: np.ndarray,
    box: tuple[int, int, int, int] | None = None,
) -> str:
    """OCR the top-center hero title; returns best raw string (may be noisy)."""
    if image.ndim != 3:
        raise ValueError("image must be BGR")
    crop = _crop_name_box(image, box)
    variants = _upscaled_name_variants(crop)
    candidates = _name_ocr_candidates(variants)
    return _best_name_candidate(candidates)


def _ocr_name_variants(probe: str) -> list[str]:
    base = "".join(ch for ch in probe.lower() if ch.isalpha() or ch in "-' &")
    base = " ".join(base.split())
    if len(base) < 2:
        return []
    variants = {base, base.replace(" ", "")}
    variants.add(base.replace("w", "j").replace("v", "b"))
    variants.add(base.replace("vv", "u"))
    variants.add(base.replace("rn", "m"))
    variants.add(base.replace("l", "i"))
    variants.add(base.replace("i", "l"))
    return [v for v in variants if len(v.replace(" ", "")) >= 2]


def _match_cleaned_name(cleaned: str, known: tuple[str, ...], lower_map: dict[str, str]) -> str | None:
    """Exact or substring match against the cleaned (letters-only) OCR name."""
    if cleaned.lower() in lower_map:
        return lower_map[cleaned.lower()]
    for name in known:
        if name.lower() in cleaned.lower() and abs(len(name) - len(cleaned)) <= 2:
            return name
    return None


def _match_probe_exact(probes: list[str], lower_map: dict[str, str]) -> str | None:
    """Exact match of any OCR-typo probe against known names, space-insensitive."""
    compact_map = {k.replace(" ", ""): v for k, v in lower_map.items()}
    for probe in probes:
        if probe in lower_map:
            return lower_map[probe]
        compact = probe.replace(" ", "")
        if compact in compact_map:
            return compact_map[compact]
    return None


def _match_probe_fuzzy(
    probes: list[str], known: tuple[str, ...], *, cutoff: float
) -> str | None:
    """Best SequenceMatcher score across probes, with a confidence guard.

    Requires a clear winner: either close to `cutoff` isn't enough on its
    own — a narrow lead over the runner-up is only trusted above 0.85/0.9
    to avoid picking an arbitrary near-tie.
    """
    fuzzy_probes = [p for p in probes if len(p.replace(" ", "")) >= 4]
    if not fuzzy_probes:
        return None

    scored: list[tuple[float, str]] = []
    for probe in fuzzy_probes:
        for name in known:
            score = SequenceMatcher(
                None, probe.replace(" ", ""), name.lower().replace(" ", "")
            ).ratio()
            scored.append((score, name))
    scored.sort(reverse=True)
    best_score, best_name = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < cutoff:
        return None
    if best_score - second < 0.08 and best_score < 0.85 and best_score < 0.9:
        return None
    return best_name


def match_known_hero_name(
    raw: str,
    known: tuple[str, ...] | list[str],
    *,
    cutoff: float = 0.62,
) -> str | None:
    """Fuzzy-match OCR text to a known hero display name."""
    if not isinstance(raw, str):
        raise ValueError(f"raw must be str; got {type(raw).__name__}")
    if not known:
        return None
    known = tuple(known)

    cleaned = clean_name(raw)
    lower_map = {n.lower(): n for n in known}

    if cleaned:
        matched = _match_cleaned_name(cleaned, known, lower_map)
        if matched is not None:
            return matched

    probes = [p for p in _ocr_name_variants(cleaned or raw) if len(p.replace(" ", "")) >= 3]
    if not probes:
        return None

    matched = _match_probe_exact(probes, lower_map)
    if matched is not None:
        return matched

    return _match_probe_fuzzy(probes, known, cutoff=cutoff)


def _resolve_rarity_ui(
    image: np.ndarray,
    rarity_hint: str | None,
    rarity_box: tuple[int, int, int, int] | None,
) -> str | None:
    if rarity_hint is not None or rarity_box is None:
        return rarity_hint
    x, y, w, h = rarity_box
    crop = image[y : y + h, x : x + w]
    return parse_rarity(pytesseract.image_to_string(crop, config="--psm 7"))


def _match_via_template(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    rarity_box: tuple[int, int, int, int] | None,
    rarity_hint: str | None,
    templates_dir: Path | str,
) -> tuple[str, str, str | None, str | None] | None:
    """Match against labeled name-crop templates; None if no template hit."""
    from ks.heroes.name_templates import load_name_templates, match_name_template

    templates = load_name_templates(Path(templates_dir))
    tmpl_name, _score = match_name_template(image, box, templates)
    if tmpl_name is None:
        return None

    raw = ocr_top_center_name(image, box)
    rarity_ui = _resolve_rarity_ui(image, rarity_hint, rarity_box)
    color = detect_rarity_color(image, rarity_box or (20, 90, 200, 120))
    return tmpl_name, raw or tmpl_name, rarity_ui, color


def _catalog_names_for_match(
    cat: dict[str, CatalogEntry],
    *,
    rarity_ui: str | None,
    color: str | None,
    troop: str | None,
) -> tuple[tuple[str, ...], str | None]:
    """Narrow catalog names by rarity/troop/color, falling back to all names.

    Blue UI chrome false-positives often; only trust orange/purple card
    colors when SSR/SR OCR is missing. Returns ``(known_names, color_filter)``.
    """
    color_filter = color if (rarity_ui is None and color in {"orange", "purple"}) else None
    known = names_for_filters(cat, rarity=rarity_ui, troop=troop, color=color_filter)
    if not known:
        known = tuple(sorted(cat.keys()))
    return known, color_filter


def resolve_hero_name(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    rarity_box: tuple[int, int, int, int] | None = None,
    rarity_hint: str | None = None,
    troop_hint: str | None = None,
    catalog: dict[str, CatalogEntry] | None = None,
    templates_dir: Path | str | None = None,
) -> tuple[str | None, str, str | None, str | None]:
    """Return (resolved_name, raw_ocr, rarity_ui, color).

    Prefers labeled name-crop templates when ``templates_dir`` has PNGs, then
    filters the catalog by rarity color / SSR badge + troop when known.
    """
    cat = catalog if catalog is not None else load_name_catalog()

    # Template match against captured name crops (trained labels).
    if templates_dir is not None:
        tmpl_result = _match_via_template(
            image,
            box,
            rarity_box=rarity_box,
            rarity_hint=rarity_hint,
            templates_dir=templates_dir,
        )
        if tmpl_result is not None:
            return tmpl_result

    raw = ocr_top_center_name(image, box)
    rarity_ui = _resolve_rarity_ui(image, rarity_hint, rarity_box)
    color = detect_rarity_color(image, rarity_box or (20, 90, 200, 120))
    troop = troop_hint or detect_troop_hint(image)

    known, color_filter = _catalog_names_for_match(
        cat, rarity_ui=rarity_ui, color=color, troop=troop
    )

    matched = match_known_hero_name(raw, known)
    if matched is None and (rarity_ui or color_filter or troop):
        matched = match_known_hero_name(raw, tuple(sorted(cat.keys())))

    if matched:
        return matched, raw, rarity_ui, color

    # Catalog-only names — do not accept raw OCR junk as a hero name.
    return None, raw, rarity_ui, color
