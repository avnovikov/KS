"""Formula-derived expedition gear stats (rarity + level + mastery)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_YAML = _ROOT / "config" / "hero_gear_optimizer" / "pieces_and_stats.yaml"

# Defaults: kingshotoptimizer.com + blue OCR calibration (2026-08-02).
_DEFAULT_TIERS: dict[str, dict[str, float | int]] = {
    "blue": {"base": 0.06, "max": 0.144, "cap": 60},
    "epic": {"base": 0.09, "max": 0.258, "cap": 80},
    "purple": {"base": 0.09, "max": 0.258, "cap": 80},
    "mythic": {"base": 0.15, "max": 0.5, "cap": 100},
    "gold": {"base": 0.15, "max": 0.5, "cap": 100},
    "red": {"base": 0.5, "max": 1.0, "cap": 200, "red_from": 100},
}

_RARITY_ALIASES = {
    "rare": "blue",
    "blue": "blue",
    "epic": "epic",
    "purple": "epic",
    "mythic": "mythic",
    "gold": "mythic",
    "red": "red",
}


def _normalize_rarity(rarity: str | None) -> str | None:
    if not rarity:
        return None
    key = rarity.strip().lower()
    return _RARITY_ALIASES.get(key, key)


@lru_cache(maxsize=4)
def load_stat_tiers(path: str | None = None) -> dict[str, dict[str, float | int]]:
    """Load base/max/cap per rarity; merge YAML ``stat_tiers`` over defaults."""
    cfg = Path(path) if path else _DEFAULT_YAML
    tiers = {k: dict(v) for k, v in _DEFAULT_TIERS.items()}
    if not cfg.is_file():
        return tiers
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    for name, entry in (raw.get("stat_tiers") or {}).items():
        key = _normalize_rarity(str(name)) or str(name).lower()
        if not isinstance(entry, dict):
            continue
        cur = dict(tiers.get(key) or {})
        if "base" in entry:
            cur["base"] = float(entry["base"])
        if "max" in entry:
            cur["max"] = float(entry["max"])
        if "cap" in entry:
            cur["cap"] = int(entry["cap"])
        if "red_from" in entry:
            cur["red_from"] = int(entry["red_from"])
        tiers[key] = cur
    return tiers


def _enhanced_red_fraction(
    level: int,
    *,
    max_stat: float,
    red_from: object,
    table: dict[str, dict[str, float | int]],
) -> float:
    anchor = int(red_from or 100)
    if level < anchor:
        mythic = table.get("mythic") or _DEFAULT_TIERS["mythic"]
        m_base = float(mythic["base"])
        m_max = float(mythic["max"])
        m_cap = float(mythic["cap"])
        return m_base + (level / m_cap) * (m_max - m_base)
    if level == anchor:
        return 0.5
    return min(0.5 + (level - anchor) * 0.005, max_stat)


def _enhanced_tier_fraction(
    level: int, *, base: float, max_stat: float, cap: int, rarity_key: str
) -> float:
    if cap <= 0:
        raise ValueError(f"invalid cap for rarity {rarity_key!r}: {cap}")
    level_clamped = min(level, cap)
    return base + (level_clamped / float(cap)) * (max_stat - base)


def expedition_stat_fraction(
    rarity: str | None,
    enhancement_level: int | None,
    mastery_level: int | None = None,
    *,
    tiers: dict[str, dict[str, float | int]] | None = None,
) -> float | None:
    """Expedition lethality/health fraction (e.g. 0.3942 = 39.42%).

    Returns None when rarity has no calibrated formula (e.g. grey/green).
    """
    key = _normalize_rarity(rarity)
    if key is None:
        return None
    table = tiers if tiers is not None else load_stat_tiers()
    entry = table.get(key)
    if entry is None:
        return None

    level = int(enhancement_level or 0)
    if level < 0:
        raise ValueError(f"enhancement_level must be >= 0; got {enhancement_level}")
    mastery = int(mastery_level or 0)
    if mastery < 0:
        raise ValueError(f"mastery_level must be >= 0; got {mastery_level}")

    base = float(entry["base"])
    max_stat = float(entry["max"])
    cap = int(entry["cap"])
    if key == "red":
        enhanced = _enhanced_red_fraction(
            level, max_stat=max_stat, red_from=entry.get("red_from"), table=table
        )
    else:
        enhanced = _enhanced_tier_fraction(
            level, base=base, max_stat=max_stat, cap=cap, rarity_key=key
        )
    return enhanced * (1.0 + 0.1 * mastery)


def ocr_stat_delta_pct(
    ocr_pct: float | None,
    rarity: str | None,
    enhancement_level: int | None,
    mastery_level: int | None = None,
) -> float | None:
    """OCR percent minus formula percent; None if either side missing."""
    if ocr_pct is None:
        return None
    frac = expedition_stat_fraction(rarity, enhancement_level, mastery_level)
    if frac is None:
        return None
    return float(ocr_pct) - (frac * 100.0)
