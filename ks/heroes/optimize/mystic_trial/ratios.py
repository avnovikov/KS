"""Troop ratio search and fill helpers for Mystic Trial rooms."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

TROOP_TYPES: tuple[str, ...] = ("infantry", "cavalry", "archers")

DEFAULT_PUBLISHED_RATIOS: tuple[dict[str, float], ...] = (
    {"infantry": 0.50, "cavalry": 0.15, "archers": 0.35},
    {"infantry": 0.55, "cavalry": 0.10, "archers": 0.35},
    {"infantry": 0.60, "cavalry": 0.10, "archers": 0.30},
    {"infantry": 0.50, "cavalry": 0.10, "archers": 0.40},
    {"infantry": 0.50, "cavalry": 0.20, "archers": 0.30},
    {"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3},
)


def normalize_ratio(raw: Mapping[str, float]) -> dict[str, float]:
    vals = {t: max(0.0, float(raw.get(t, 0.0))) for t in TROOP_TYPES}
    total = sum(vals.values())
    if total <= 0:
        raise ValueError(f"ratio must have positive mass; got {dict(raw)}")
    return {t: vals[t] / total for t in TROOP_TYPES}


def ratio_candidates(
    *,
    step: float = 0.05,
    published: Sequence[Mapping[str, float]] | None = None,
) -> list[dict[str, float]]:
    """Published seeds plus ±step grid on two axes (third residual)."""
    seen: set[tuple[float, float, float]] = set()
    out: list[dict[str, float]] = []

    def add(raw: Mapping[str, float]) -> None:
        r = normalize_ratio(raw)
        key = (round(r["infantry"], 6), round(r["cavalry"], 6), round(r["archers"], 6))
        if key in seen:
            return
        seen.add(key)
        out.append(r)

    for pub in published if published is not None else DEFAULT_PUBLISHED_RATIOS:
        add(pub)

    n = int(round(1.0 / step))
    for i in range(n + 1):
        for c in range(n + 1 - i):
            inf = i * step
            cav = c * step
            arch = 1.0 - inf - cav
            if arch < -1e-9:
                continue
            add({"infantry": inf, "cavalry": cav, "archers": max(0.0, arch)})
    return out


def counts_for_ratio(
    ratio: Mapping[str, float],
    capacity: int,
    owned: Mapping[str, int],
) -> dict[str, int]:
    """Largest-remainder allocation, capped by owned inventory."""
    if capacity < 0:
        raise ValueError(f"capacity must be >= 0; got {capacity}")
    r = normalize_ratio(ratio)
    soft_cap = min(
        int(capacity),
        sum(max(0, int(owned.get(t, 0))) for t in TROOP_TYPES),
    )
    if soft_cap == 0:
        return {t: 0 for t in TROOP_TYPES}

    exact = {t: r[t] * soft_cap for t in TROOP_TYPES}
    floors = {t: int(math.floor(exact[t])) for t in TROOP_TYPES}
    for t in TROOP_TYPES:
        floors[t] = min(floors[t], max(0, int(owned.get(t, 0))))
    rem = soft_cap - sum(floors.values())
    order = sorted(
        TROOP_TYPES,
        key=lambda t: (exact[t] - math.floor(exact[t]), r[t]),
        reverse=True,
    )
    for t in order:
        if rem <= 0:
            break
        room = max(0, int(owned.get(t, 0)) - floors[t])
        take = min(room, rem)
        floors[t] += take
        rem -= take
    return floors
