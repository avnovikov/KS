"""Attrition MC utility for Radiant search (evaluate only — not the optimiser)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ks.heroes.optimize.mystic_trial.fight_utility import (
    UtilityResult,
    evaluate_attrition,
)
from ks.heroes.optimize.mystic_trial.proxy import MarchScore


def _score(
    *,
    offense: float,
    tough: float,
    n_i: float = 1000.0,
    n_c: float = 1000.0,
    n_a: float = 1000.0,
) -> MarchScore:
    total_n = n_i + n_c + n_a
    return MarchScore(
        score=offense + tough,
        offense_sum=offense,
        tough_sum=tough,
        by_type={
            "infantry": {
                "n": n_i,
                "offense": offense * (n_i / total_n),
                "tough": tough * (n_i / total_n),
            },
            "cavalry": {
                "n": n_c,
                "offense": offense * (n_c / total_n),
                "tough": tough * (n_c / total_n),
            },
            "archers": {
                "n": n_a,
                "offense": offense * (n_a / total_n),
                "tough": tough * (n_a / total_n),
            },
        },
    )


def test_utility_result_win_rate_in_unit_interval() -> None:
    player = _score(offense=1e6, tough=1e6)
    enemy = _score(offense=1e6, tough=1e6)
    result = evaluate_attrition(player, enemy, trials=16, rounds=10, seed=1)
    assert isinstance(result, UtilityResult)
    assert 0.0 <= result.win_rate <= 1.0
    assert result.trials == 16
    assert result.rounds == 10


def test_stronger_player_wins_more_often() -> None:
    weak = _score(offense=1e5, tough=1e5)
    strong = _score(offense=5e6, tough=5e6)
    enemy = _score(offense=1e6, tough=1e6)
    wr_weak = evaluate_attrition(weak, enemy, trials=64, rounds=10, seed=7).win_rate
    wr_strong = evaluate_attrition(strong, enemy, trials=64, rounds=10, seed=7).win_rate
    assert wr_strong > wr_weak


def test_same_seed_is_deterministic() -> None:
    player = _score(offense=1.2e6, tough=1.1e6)
    enemy = _score(offense=1.0e6, tough=1.0e6)
    a = evaluate_attrition(player, enemy, trials=32, rounds=8, seed=42)
    b = evaluate_attrition(player, enemy, trials=32, rounds=8, seed=42)
    assert a.win_rate == b.win_rate
    assert a.remaining_hp_est == b.remaining_hp_est


def test_to_dict_shape() -> None:
    player = _score(offense=1e6, tough=1e6)
    enemy = _score(offense=1e6, tough=1e6)
    d: dict[str, Any] = evaluate_attrition(
        player, enemy, trials=4, rounds=5, seed=0
    ).to_dict()
    assert set(d) >= {
        "win_rate",
        "remaining_hp_est",
        "rounds",
        "trials",
        "player_score",
        "enemy_score",
    }
