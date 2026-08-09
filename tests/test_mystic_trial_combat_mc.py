"""Floor combat engine tests (#38)."""

from __future__ import annotations

from ks.heroes.optimize.mystic_trial.combat_mc import simulate_floor
from ks.heroes.optimize.mystic_trial.floors import FloorStub, empty_enemy_bonuses
from ks.heroes.optimize.mystic_trial.proxy import MarchScore


def _score(val: float) -> MarchScore:
    return MarchScore(
        score=val,
        offense_sum=val,
        tough_sum=val,
        by_type={
            "infantry": {"n": 1, "offense": val / 3, "tough": val / 3},
            "cavalry": {"n": 1, "offense": val / 3, "tough": val / 3},
            "archers": {"n": 1, "offense": val / 3, "tough": val / 3},
        },
    )


def _stub(floor: int, ratio: dict[str, float], scale: float) -> FloorStub:
    return FloorStub(
        floor=floor,
        enemy_ratio=ratio,
        enemy_power_scale=scale,
        enemy_bonuses=empty_enemy_bonuses(),
    )


def test_simulate_floor_win_rate_in_unit_interval() -> None:
    stub = _stub(
        10,
        {"infantry": 0.53, "cavalry": 0.27, "archers": 0.20},
        1.0,
    )
    result = simulate_floor(_score(1000.0), stub)
    assert 0.0 <= result.win_rate <= 1.0
    assert result.rounds == 10


def test_harder_floor_lowers_win_rate() -> None:
    easy = _stub(1, {"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3}, 1.0)
    hard = _stub(10, {"infantry": 0.53, "cavalry": 0.27, "archers": 0.20}, 2.0)
    player = _score(1000.0)
    assert simulate_floor(player, hard).win_rate < simulate_floor(player, easy).win_rate
