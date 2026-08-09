"""Layered Radiant search helpers — ratio grid constrained by lineup troops."""

from __future__ import annotations

import pytest

from ks.heroes.optimize.mystic_trial.radiant_search import (
    ratio_candidates_for_lineup,
    search_best_ratio,
)
from ks.heroes.optimize.mystic_trial.ratios import counts_for_ratio
from ks.heroes.optimize.mystic_trial.fight_utility import evaluate_attrition
from ks.heroes.optimize.mystic_trial.proxy import MarchScore, score_march
from ks.heroes.optimize.troop_stats import TroopUnitStats


def _unit() -> TroopUnitStats:
    return TroopUnitStats(attack=100.0, defense=10.0, lethality=10.0, health=300.0)


def test_ratio_candidates_respect_min_share_for_lineup_troops() -> None:
    cands = ratio_candidates_for_lineup(
        {"infantry", "cavalry", "archers"},
        published=[{"infantry": 0.5, "cavalry": 0.15, "archers": 0.35}],
        step=0.05,
        min_share=0.05,
    )
    assert cands
    for r in cands:
        assert r["cavalry"] >= 0.05 - 1e-9
        assert r["infantry"] >= 0.05 - 1e-9
        assert r["archers"] >= 0.05 - 1e-9


def test_ratio_candidates_allow_zero_when_troop_absent() -> None:
    cands = ratio_candidates_for_lineup(
        {"infantry", "archers"},  # no cavalry hero
        published=[{"infantry": 0.5, "cavalry": 0.15, "archers": 0.35}],
        step=0.05,
        min_share=0.05,
    )
    assert any(r["cavalry"] < 1e-9 for r in cands)


def test_search_best_ratio_keeps_cavalry_when_cav_hero() -> None:
    units = {t: _unit() for t in ("infantry", "cavalry", "archers")}
    atk = {t: 50.0 for t in units}
    # Boost cavalry so a cav-heavy mix can win, but constraint is the point.
    atk["cavalry"] = 5.0  # weak cav — optimiser might prefer 0 without constraint
    def_pct = {t: 20.0 for t in units}
    leth = {t: 20.0 for t in units}
    hp = {t: 20.0 for t in units}
    enemy = score_march(
        {"infantry": 50000, "cavalry": 50000, "archers": 50000},
        units,
        atk_pct={t: 40.0 for t in units},
        def_pct=def_pct,
        leth_pct=leth,
        hp_pct=hp,
    )

    def evaluate(player: MarchScore) -> float:
        return evaluate_attrition(
            player, enemy, trials=24, rounds=8, seed=3
        ).win_rate

    best = search_best_ratio(
        capacity=150_000,
        owned={t: 150_000 for t in units},
        units=units,
        atk_pct=atk,
        def_pct=def_pct,
        leth_pct=leth,
        hp_pct=hp,
        lineup_troops={"infantry", "cavalry", "archers"},
        published=[{"infantry": 0.5, "cavalry": 0.15, "archers": 0.35}],
        step=0.05,
        min_share=0.05,
        evaluate=evaluate,
    )
    assert best["counts"]["cavalry"] > 0
    assert best["ratio"]["cavalry"] >= 0.05 - 1e-9
    assert 0.0 <= best["win_rate"] <= 1.0
