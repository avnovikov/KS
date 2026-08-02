"""Scale stored naked hero power when stars/pellets change."""

from __future__ import annotations

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
