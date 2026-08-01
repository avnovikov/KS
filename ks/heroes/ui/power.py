"""Estimate gear power from rarity + enhancement + mastery.

Curves fitted to scraped inventory (blue/green exact; epic/mythic least-squares
against OCR powers, with mastery as ×(1 + 0.1·M) matching expedition stats).
"""

from __future__ import annotations

# demastered_power ≈ intercept + slope * enhancement
# final_power = round(demastered * (1 + 0.1 * mastery))
_RARITY_LINEAR: dict[str, tuple[float, float]] = {
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


def normalize_rarity(rarity: str | None) -> str:
    key = (rarity or "blue").strip().lower()
    if key not in _RARITY_LINEAR:
        # Unknown OCR rarity — treat like blue (common mid-tier shell)
        return "blue"
    return key


def compute_gear_power(
    rarity: str | None,
    enhancement_level: int | None,
    mastery_level: int | None = None,
) -> int:
    """Return estimated UI power for the given progression."""
    intercept, slope = _RARITY_LINEAR[normalize_rarity(rarity)]
    enh = int(enhancement_level or 0)
    if enh < 0:
        enh = 0
    mast = int(mastery_level or 0)
    if mast < 0:
        mast = 0
    demastered = intercept + slope * float(enh)
    return int(round(demastered * (1.0 + 0.1 * mast)))
