"""Scale stored naked hero power when stars/pellets or level change."""

from __future__ import annotations

from typing import Any

from ks.heroes.optimize.hero_level_ladder import (
    level_power_factor,
    load_hero_level_ladder,
)
from ks.heroes.optimize.scoring import star_progress_factor


def scale_power_for_star_change(
    power: int | None,
    old_stars: int | None,
    old_pellets: int | None,
    new_stars: int | None,
    new_pellets: int | None,
) -> int | None:
    """Rescale OCR baseline power by star_progress_factor ratio.

    Returns None when power is missing. Leaves power unchanged when the old
    factor is non-positive (should not happen for the standard curve).
    """
    if power is None:
        return None
    old_f = star_progress_factor(old_stars, old_pellets)
    new_f = star_progress_factor(new_stars, new_pellets)
    if old_f <= 0:
        return int(power)
    return max(0, round(int(power) * new_f / old_f))


def scale_power_for_level_change(
    power: int | None,
    old_level: int | None,
    new_level: int | None,
    *,
    ladder: dict[str, Any] | None = None,
) -> int | None:
    """Rescale naked power by scraped level power_factor ratio.

    Returns None when power is missing. Leaves power unchanged when levels are
    missing/equal or the old factor is non-positive.
    """
    if power is None:
        return None
    if old_level is None or new_level is None:
        return int(power)
    if int(old_level) == int(new_level):
        return int(power)
    table = ladder or load_hero_level_ladder()
    old_f = level_power_factor(table, int(old_level))
    new_f = level_power_factor(table, int(new_level))
    if old_f <= 0:
        return int(power)
    return max(0, round(int(power) * new_f / old_f))
