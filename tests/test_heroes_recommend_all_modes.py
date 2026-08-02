"""Batch recommend: all sword/bear modes with points."""

from __future__ import annotations

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.recommend import recommend_all_modes
from ks.heroes.optimize.types import CatalogEntry, EffectTag, Scenario, TroopsConfig


def _hero(name: str, *, power: int = 1000) -> HeroRecord:
    return HeroRecord(name=name, power=power, escorts=5, stars=5)


def _cat(name: str, troop: str, widget: str, kind: str, value: float) -> CatalogEntry:
    applies = "widget" if "rally" in kind or "defender" in kind else "expedition"
    return CatalogEntry(
        name=name,
        troop=troop,
        widget_type=widget,
        effects=(EffectTag(kind, value, applies),),
    )


def test_recommend_all_modes_returns_each_mode() -> None:
    heroes = [
        _hero("Zoe"),
        _hero("Saul"),
        _hero("Howard"),
        _hero("Amadeus"),
        _hero("Jabel"),
        _hero("Chenko"),
    ]
    catalog = {
        "Zoe": _cat("Zoe", "infantry", "defense", "defender_attack", 30),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 20),
        "Howard": _cat("Howard", "cavalry", "none", "damage_taken_down", 20),
        "Amadeus": _cat("Amadeus", "infantry", "attack", "rally_attack", 30),
        "Jabel": _cat("Jabel", "cavalry", "attack", "rally_attack", 25),
        "Chenko": _cat("Chenko", "archer", "none", "attack_up", 15),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=40,
            personal_rate=600,
            enemy_power_scale=100000,
            require_widget="defense",
            formation_weights={"infantry": 1.2, "cavalry": 0.6, "archers": 0.8},
        ),
        "rally_lead": Scenario(
            mode="rally_lead",
            combat_rate=80,
            minutes_held=0,
            personal_rate=0,
            p_first=0.2,
            first_bonus=500,
            enemy_power_scale=100000,
            require_widget="attack",
            formation_weights={"infantry": 0.3, "cavalry": 0.6, "archers": 1.3},
        ),
        "joiner": Scenario(
            mode="joiner",
            combat_rate=20,
            minutes_held=0,
            personal_rate=0,
            p_first=0.1,
            first_bonus=100,
            enemy_power_scale=100000,
            formation_weights={"infantry": 0.5, "cavalry": 0.8, "archers": 1.0},
        ),
        "solo": Scenario(
            mode="solo",
            combat_rate=30,
            minutes_held=0,
            personal_rate=0,
            enemy_power_scale=50000,
            formation_weights={"infantry": 0.8, "cavalry": 0.8, "archers": 0.8},
        ),
    }
    results = recommend_all_modes(heroes, catalog, troops, scenarios)
    assert set(results) == {"garrison", "rally_lead", "joiner", "solo"}
    for mode, result in results.items():
        assert result.recommended_mode == mode
        assert result.expected_personal_points > 0
        assert len(result.heroes) == 3


def test_recommend_all_modes_keeps_feasible_when_one_mode_fails() -> None:
    """Attack-only roster: garrison infeasible, other modes still returned."""
    heroes = [
        _hero("Amadeus"),
        _hero("Jabel"),
        _hero("Chenko"),
        _hero("Howard"),
    ]
    catalog = {
        "Amadeus": _cat("Amadeus", "infantry", "attack", "rally_attack", 30),
        "Jabel": _cat("Jabel", "cavalry", "attack", "rally_attack", 25),
        "Chenko": _cat("Chenko", "archer", "none", "attack_up", 15),
        "Howard": _cat("Howard", "cavalry", "none", "damage_taken_down", 20),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=40,
            personal_rate=600,
            enemy_power_scale=100000,
            require_widget="defense",
            formation_weights={"infantry": 1.2, "cavalry": 0.6, "archers": 0.8},
        ),
        "rally_lead": Scenario(
            mode="rally_lead",
            combat_rate=80,
            minutes_held=0,
            personal_rate=0,
            p_first=0.2,
            first_bonus=500,
            enemy_power_scale=100000,
            require_widget="attack",
            formation_weights={"infantry": 0.3, "cavalry": 0.6, "archers": 1.3},
        ),
        "solo": Scenario(
            mode="solo",
            combat_rate=30,
            minutes_held=0,
            personal_rate=0,
            enemy_power_scale=50000,
            formation_weights={"infantry": 0.8, "cavalry": 0.8, "archers": 0.8},
        ),
    }
    results = recommend_all_modes(heroes, catalog, troops, scenarios)
    assert "garrison" not in results
    assert "rally_lead" in results
    assert "solo" in results
