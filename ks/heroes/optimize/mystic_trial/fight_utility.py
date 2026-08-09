"""Fight utility for Radiant — attrition Monte Carlo (evaluate only).

The optimiser proposes candidates; this module scores them. Swap the body
later for a tick/skill sim without changing the search API.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from ks.heroes.optimize.mystic_trial.proxy import MarchScore
from ks.heroes.optimize.mystic_trial.ratios import TROOP_TYPES


@dataclass(frozen=True)
class UtilityResult:
    win_rate: float
    remaining_hp_est: float
    rounds: int
    trials: int
    player_score: float
    enemy_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "win_rate": self.win_rate,
            "remaining_hp_est": self.remaining_hp_est,
            "rounds": self.rounds,
            "trials": self.trials,
            "player_score": self.player_score,
            "enemy_score": self.enemy_score,
        }


def evaluate_attrition(
    player: MarchScore,
    enemy: MarchScore,
    *,
    trials: int = 32,
    rounds: int = 10,
    seed: int = 0,
    noise: float = 0.15,
) -> UtilityResult:
    """Multi-round troop attrition with light per-round noise.

    Each side's HP pool starts at ``tough_sum``. Each round deals damage
    ``offense × (1 + U[-noise, noise])`` to the other side. A trial is a win
    if the enemy HP hits 0 first (or player has more HP at the round cap).
    """
    if trials < 1:
        raise ValueError(f"trials must be >= 1; got {trials}")
    if rounds < 1:
        raise ValueError(f"rounds must be >= 1; got {rounds}")
    if noise < 0:
        raise ValueError(f"noise must be >= 0; got {noise}")

    rng = random.Random(int(seed))
    p_off = max(0.0, float(player.offense_sum))
    e_off = max(0.0, float(enemy.offense_sum))
    p_hp0 = max(1e-9, float(player.tough_sum))
    e_hp0 = max(1e-9, float(enemy.tough_sum))

    wins = 0
    rem_sum = 0.0
    for _ in range(int(trials)):
        p_hp = p_hp0
        e_hp = e_hp0
        for _r in range(int(rounds)):
            if p_hp <= 0 or e_hp <= 0:
                break
            p_mult = 1.0 + rng.uniform(-noise, noise)
            e_mult = 1.0 + rng.uniform(-noise, noise)
            e_hp -= p_off * max(0.0, p_mult)
            p_hp -= e_off * max(0.0, e_mult)
        player_alive = p_hp > 0
        enemy_alive = e_hp > 0
        if player_alive and not enemy_alive:
            wins += 1
            rem_sum += p_hp / p_hp0
        elif player_alive and enemy_alive:
            # Round cap: higher remaining fraction wins.
            if (p_hp / p_hp0) > (e_hp / e_hp0):
                wins += 1
            rem_sum += (p_hp - e_hp) / max(p_hp0, e_hp0)
        else:
            rem_sum += -1.0 if not player_alive else 0.0

    win_rate = wins / float(trials)
    remaining = rem_sum / float(trials)
    remaining = min(1.0, max(-1.0, remaining))
    return UtilityResult(
        win_rate=win_rate,
        remaining_hp_est=remaining,
        rounds=int(rounds),
        trials=int(trials),
        player_score=float(player.score),
        enemy_score=float(enemy.score),
    )


def lineup_troop_types(hero_troops: list[str] | tuple[str, ...]) -> set[str]:
    """Normalize hero troop labels present in a lineup."""
    out: set[str] = set()
    for raw in hero_troops:
        key = str(raw or "").strip().lower()
        if key in ("archer", "archers"):
            out.add("archers")
        elif key in TROOP_TYPES:
            out.add(key)
    return out


__all__ = [
    "UtilityResult",
    "evaluate_attrition",
    "lineup_troop_types",
]
