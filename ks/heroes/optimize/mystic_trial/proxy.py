"""Geometric-mean march proxy for Mystic Trial rooms."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ks.heroes.optimize.mystic_trial.ratios import TROOP_TYPES
from ks.heroes.optimize.troop_stats import TroopUnitStats

PROXY_BANNER = "Proxy score — not in-game clear prediction."


@dataclass(frozen=True)
class MarchScore:
    score: float
    offense_sum: float
    tough_sum: float
    by_type: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "offense_sum": self.offense_sum,
            "tough_sum": self.tough_sum,
            "by_type": {k: dict(v) for k, v in self.by_type.items()},
        }


def score_march(
    counts: Mapping[str, int],
    units: Mapping[str, TroopUnitStats | None],
    *,
    atk_pct: Mapping[str, float],
    def_pct: Mapping[str, float],
    leth_pct: Mapping[str, float],
    hp_pct: Mapping[str, float],
) -> MarchScore:
    """Geometric-mean proxy √(Σoffense × Σtough)."""
    offense_sum = 0.0
    tough_sum = 0.0
    by_type: dict[str, dict[str, float]] = {}
    for troop in TROOP_TYPES:
        n = int(counts.get(troop, 0) or 0)
        unit = units.get(troop)
        if n <= 0 or unit is None:
            by_type[troop] = {"n": float(n), "offense": 0.0, "tough": 0.0}
            continue
        atk_m = 1.0 + float(atk_pct.get(troop, 0.0)) / 100.0
        def_m = 1.0 + float(def_pct.get(troop, 0.0)) / 100.0
        leth_m = 1.0 + float(leth_pct.get(troop, 0.0)) / 100.0
        hp_m = 1.0 + float(hp_pct.get(troop, 0.0)) / 100.0
        offense = n * unit.attack * atk_m * (unit.lethality / 100.0) * leth_m
        tough = n * unit.defense * def_m * unit.health * hp_m
        by_type[troop] = {"n": float(n), "offense": offense, "tough": tough}
        offense_sum += offense
        tough_sum += tough
    score = math.sqrt(max(0.0, offense_sum) * max(0.0, tough_sum))
    return MarchScore(
        score=score,
        offense_sum=offense_sum,
        tough_sum=tough_sum,
        by_type=by_type,
    )
