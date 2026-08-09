"""Layered Radiant search: ratio knapsack grid under lineup constraints.

Hero/gear layers stay in ``optimize_radiant`` for v1; this module owns the
troop-ratio search given a fixed lineup + percent maps + utility callback.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ks.heroes.optimize.mystic_trial.proxy import MarchScore, score_march
from ks.heroes.optimize.mystic_trial.ratios import (
    TROOP_TYPES,
    counts_for_ratio,
    normalize_ratio,
    ratio_candidates,
)
from ks.heroes.optimize.troop_stats import TroopUnitStats


def ratio_candidates_for_lineup(
    lineup_troops: set[str] | frozenset[str],
    *,
    published: Sequence[Mapping[str, float]] | None = None,
    step: float = 0.05,
    min_share: float = 0.05,
) -> list[dict[str, float]]:
    """Ratio grid filtered so present lineup troop types keep ``min_share``."""
    if min_share < 0 or min_share > 1:
        raise ValueError(f"min_share must be in [0, 1]; got {min_share}")
    required = {t for t in lineup_troops if t in TROOP_TYPES}
    if required and min_share * len(required) > 1.0 + 1e-9:
        raise ValueError(
            f"min_share {min_share} impossible for {len(required)} troop types"
        )
    out: list[dict[str, float]] = []
    for raw in ratio_candidates(step=step, published=published):
        r = normalize_ratio(raw)
        if any(r[t] + 1e-12 < min_share for t in required):
            continue
        out.append(r)
    if not out and required:
        # Degenerate fallback: equal split among required, zeros elsewhere.
        share = 1.0 / len(required)
        out.append(
            normalize_ratio({t: share if t in required else 0.0 for t in TROOP_TYPES})
        )
    return out


def search_best_ratio(
    *,
    capacity: int,
    owned: Mapping[str, int],
    units: Mapping[str, TroopUnitStats | None],
    atk_pct: Mapping[str, float],
    def_pct: Mapping[str, float],
    leth_pct: Mapping[str, float],
    hp_pct: Mapping[str, float],
    lineup_troops: set[str] | frozenset[str],
    evaluate: Callable[[MarchScore], float],
    published: Sequence[Mapping[str, float]] | None = None,
    step: float = 0.05,
    min_share: float = 0.05,
) -> dict[str, Any]:
    """Grid-search troop mixes; maximise ``evaluate(player_march_score)``."""
    best: dict[str, Any] | None = None
    best_key: float | None = None
    for ratio in ratio_candidates_for_lineup(
        set(lineup_troops),
        published=published,
        step=step,
        min_share=min_share,
    ):
        counts = counts_for_ratio(ratio, capacity, owned)
        scored = score_march(
            counts,
            units,
            atk_pct=atk_pct,
            def_pct=def_pct,
            leth_pct=leth_pct,
            hp_pct=hp_pct,
        )
        utility = float(evaluate(scored))
        if best is None or best_key is None or utility > best_key:
            best_key = utility
            best = {
                "ratio": dict(ratio),
                "counts": dict(counts),
                "proxy": scored,
                "win_rate": utility,
            }
    if best is None:
        raise RuntimeError("ratio search produced no candidates")
    return best


__all__ = [
    "ratio_candidates_for_lineup",
    "search_best_ratio",
]
