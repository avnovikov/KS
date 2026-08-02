"""Estimate gear power from rarity + enhancement + mastery.

Curves fitted to scraped inventory (blue/green exact; epic/mythic least-squares
against OCR powers, with mastery as ×(1 + 0.1·M) matching expedition stats).
"""

from __future__ import annotations

# demastered_power ≈ intercept + slope * enhancement
# final_power = round(demastered * (1 + 0.1 * mastery))
_RARITY_LINEAR: dict[str, tuple[float, float]] = {
    "grey": (4500.0, 168.0),
    "gray": (4500.0, 168.0),
    "common": (4500.0, 168.0),
    "white": (4500.0, 168.0),
    "green": (9112.25, 340.625),
    "uncommon": (9112.25, 340.625),
    "blue": (14750.0, 516.0),
    "rare": (14750.0, 516.0),
    "epic": (16374.09415121, 1107.94579173),
    "purple": (16374.09415121, 1107.94579173),
    # Calibrated so +30 → 98550 and +51 M2 → 152100
    "mythic": (58264.28571428572, 1342.857142857143),
    "gold": (58264.28571428572, 1342.857142857143),
    "red": (58264.28571428572, 1342.857142857143),
}


def known_rarity(rarity: str | None) -> bool:
    """True when rarity maps to a fitted power curve (not a silent fallback)."""
    if rarity is None or not str(rarity).strip():
        return False
    return str(rarity).strip().lower() in _RARITY_LINEAR


def normalize_rarity(rarity: str | None) -> str:
    key = (rarity or "").strip().lower()
    if key not in _RARITY_LINEAR:
        raise ValueError(f"unknown gear rarity {rarity!r}")
    return key


def compute_gear_power(
    rarity: str | None,
    enhancement_level: int | None,
    mastery_level: int | None = None,
) -> int:
    """Return estimated UI power for the given progression."""
    if enhancement_level is None:
        raise ValueError("enhancement_level is required to estimate power")
    intercept, slope = _RARITY_LINEAR[normalize_rarity(rarity)]
    enh = int(enhancement_level)
    if enh < 0 or enh > 200:
        raise ValueError(f"enhancement_level must be 0..200; got {enh}")
    mast = int(mastery_level or 0)
    if mast < 0 or mast > 20:
        raise ValueError(f"mastery_level must be 0..20; got {mast}")
    demastered = intercept + slope * float(enh)
    return int(round(demastered * (1.0 + 0.1 * mast)))


def estimate_enhancement_from_power(
    rarity: str | None,
    power: int | None,
    mastery_level: int | None = None,
    *,
    abs_tol: int = 50,
    rel_tol: float = 0.02,
) -> int | None:
    """Invert the power curve to recover enhancement when OCR misses +N.

    When mastery is unknown, non-mythic pieces assume mastery 0. Mythic may
    include hidden ``Lv. N`` in power, so mastery 0..5 is searched there.
    """
    if power is None or not known_rarity(rarity):
        return None
    try:
        power_i = int(power)
    except (TypeError, ValueError):
        return None
    if power_i <= 0:
        return None
    rarity_key = normalize_rarity(rarity)
    intercept, slope = _RARITY_LINEAR[rarity_key]
    if slope == 0:
        return None

    if mastery_level is not None:
        mast_options = (int(mastery_level),)
    elif rarity_key in {"mythic", "gold", "red"}:
        mast_options = tuple(range(0, 6))
    else:
        mast_options = (0,)

    tol = max(abs_tol, int(rel_tol * power_i))
    best: tuple[int, int] | None = None  # (abs_err, enhancement)
    for mast in mast_options:
        if mast < 0 or mast > 20:
            continue
        demastered = float(power_i) / (1.0 + 0.1 * mast)
        nearest = int(round((demastered - intercept) / slope))
        if nearest < 0 or nearest > 200:
            continue
        estimated = compute_gear_power(rarity, nearest, mast)
        err = abs(estimated - power_i)
        if err > tol:
            continue
        if best is None or err < best[0]:
            best = (err, nearest)
    return None if best is None else best[1]


# Canonical rarity names (one per colour) for power-curve lookup and UI legend.
_CANONICAL_RARITY = ["grey", "green", "blue", "epic", "mythic"]


def rarity_power_curves(max_enhancement: int = 80) -> dict[str, list[float]]:
    """Return {rarity: [power_at_enh_0, power_at_enh_1, ..., power_at_enh_max]}.

    Only includes canonical rarities (grey/green/blue/epic/mythic).
    Values are mastery-0 powers for each enhancement level 0..max_enhancement.
    """
    curves: dict[str, list[float]] = {}
    for rarity in _CANONICAL_RARITY:
        intercept, slope = _RARITY_LINEAR[rarity]
        curves[rarity] = [
            int(round(intercept + slope * enh))
            for enh in range(max_enhancement + 1)
        ]
    return curves
