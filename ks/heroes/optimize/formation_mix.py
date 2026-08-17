"""PvP troop fill: survival infantry floor, then √n leftover.

Linear formation_weights alone always corner-solve to the highest-weight
type. Infantry lasts the rally; leftover troops follow diminishing
returns a_k / √t_k (same shape as Bear fill).
"""

from __future__ import annotations

import math

from ks.heroes.optimize.types import SurvivalFill

TROOP_TYPES = ("infantry", "cavalry", "archers")


def _validate_policy(policy: SurvivalFill) -> None:
    if policy.infantry_beta < 0:
        raise ValueError(f"infantry_beta must be >= 0; got {policy.infantry_beta}")
    for name, frac in (
        ("infantry_max_frac", policy.infantry_max_frac),
        ("infantry_min_frac", policy.infantry_min_frac),
        ("min_type_frac", policy.min_type_frac),
    ):
        if not 0.0 <= frac <= 1.0:
            raise ValueError(f"{name} must be in [0, 1]; got {frac}")
    if policy.infantry_min_frac > policy.infantry_max_frac:
        raise ValueError(
            "infantry_min_frac must be <= infantry_max_frac; "
            f"got {policy.infantry_min_frac} > {policy.infantry_max_frac}"
        )


def survival_floors(
    owned: dict[str, int],
    capacity: int,
    policy: SurvivalFill,
) -> dict[str, int]:
    """Minimum troops: β√fill infantry wall plus a small per-type presence."""
    if capacity < 0:
        raise ValueError(f"capacity must be non-negative; got {capacity}")
    _validate_policy(policy)
    owned_counts = {name: max(0, int(owned.get(name, 0))) for name in TROOP_TYPES}
    fill = min(capacity, sum(owned_counts.values()))
    if fill <= 0:
        return {name: 0 for name in TROOP_TYPES}

    presence = {
        name: min(owned_counts[name], int(policy.min_type_frac * fill))
        for name in TROOP_TYPES
    }
    inf_from_beta = int(policy.infantry_beta * math.sqrt(fill))
    inf_from_min = int(policy.infantry_min_frac * fill)
    inf_cap = int(policy.infantry_max_frac * fill)
    infantry = min(
        owned_counts["infantry"],
        inf_cap,
        max(inf_from_beta, inf_from_min, presence["infantry"]),
    )
    floors = {
        "infantry": infantry,
        "cavalry": presence["cavalry"],
        "archers": presence["archers"],
    }
    extra = sum(floors.values()) - fill
    if extra <= 0:
        return floors
    for name in ("archers", "cavalry", "infantry"):
        take = min(extra, floors[name])
        floors[name] -= take
        extra -= take
        if extra <= 0:
            break
    return floors


def fill_after_floors(
    owned: dict[str, int],
    capacity: int,
    floors: dict[str, int],
    attractiveness: dict[str, float],
) -> dict[str, int]:
    """Start at ``floors`` and give leftover to max a_k / √(t_k+1)."""
    if capacity < 0:
        raise ValueError(f"capacity must be non-negative; got {capacity}")
    owned_counts = {name: max(0, int(owned.get(name, 0))) for name in TROOP_TYPES}
    fill = min(capacity, sum(owned_counts.values()))
    counts = {
        name: min(max(0, int(floors.get(name, 0))), owned_counts[name])
        for name in TROOP_TYPES
    }
    extra = sum(counts.values()) - fill
    if extra > 0:
        for name in ("archers", "cavalry", "infantry"):
            take = min(extra, counts[name])
            counts[name] -= take
            extra -= take
            if extra <= 0:
                break

    attract = {
        name: max(0.0, float(attractiveness.get(name, 1.0))) for name in TROOP_TYPES
    }
    if sum(attract.values()) <= 0:
        attract = {name: 1.0 for name in TROOP_TYPES}

    used = sum(counts.values())
    chunk = max(1, fill // 200) if fill else 1
    while used < fill:
        left = fill - used
        best_name: str | None = None
        best_rank = -1.0
        for name in TROOP_TYPES:
            room = min(left, owned_counts[name] - counts[name], chunk)
            if room <= 0:
                continue
            rank = attract[name] / math.sqrt(counts[name] + 1)
            if rank > best_rank:
                best_rank = rank
                best_name = name
        if best_name is None:
            break
        add = min(left, owned_counts[best_name] - counts[best_name], chunk)
        counts[best_name] += add
        used += add
    return counts
