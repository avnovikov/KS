"""Governor troop bonuses in Bear Trap damage (OG-03)."""

from __future__ import annotations

import pytest

from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.optimize.bear_damage import simulate_from_units
from ks.heroes.optimize.troop_stats import TroopUnitStats


def _unit(*, attack: float = 100.0, lethality: float = 10.0) -> TroopUnitStats:
    return TroopUnitStats(
        attack=attack, defense=50.0, lethality=lethality, health=500.0
    )


def _gov(*, archer_atk: float = 0.0) -> GovernorTroopBonuses:
    return GovernorTroopBonuses(
        attack_pct={
            "infantry": 0.0,
            "cavalry": 0.0,
            "archers": archer_atk,
        },
        defense_pct={"infantry": 0.0, "cavalry": 0.0, "archers": 0.0},
        set_attack_pct=0.0,
        set_defense_pct=0.0,
        set_tier=None,
    )


def test_bear_damage_rises_with_governor_attack_pct() -> None:
    units = {
        "infantry": _unit(),
        "cavalry": _unit(),
        "archers": _unit(attack=120.0),
    }
    counts = {"infantry": 1000, "cavalry": 500, "archers": 2000}
    base = simulate_from_units(
        units, counts, skillmod=1.0, trap_attack_bonus=0.25, governor=None
    )
    buffed = simulate_from_units(
        units,
        counts,
        skillmod=1.0,
        trap_attack_bonus=0.25,
        governor=_gov(archer_atk=50.0),
    )
    assert buffed.score > base.score
    assert buffed.by_type["archers"].attack_per_troop == pytest.approx(
        base.by_type["archers"].attack_per_troop * 1.5
    )


def test_empty_governor_matches_baseline() -> None:
    units = {"infantry": _unit(), "cavalry": None, "archers": None}
    counts = {"infantry": 500, "cavalry": 0, "archers": 0}
    base = simulate_from_units(units, counts, skillmod=2.0, trap_attack_bonus=0.25)
    empty = simulate_from_units(
        units,
        counts,
        skillmod=2.0,
        trap_attack_bonus=0.25,
        governor=_gov(archer_atk=0.0),
    )
    assert empty.score == base.score
