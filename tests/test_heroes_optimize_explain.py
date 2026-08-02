"""Structured explainability + leave-one-out marginals."""

from __future__ import annotations

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.arena import load_arena_roles, optimize_arena_attack
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.types import CatalogEntry, EffectTag, Scenario, TroopsConfig


def _hero(name: str, *, power: int = 1000, escorts: int = 5) -> HeroRecord:
    return HeroRecord(name=name, power=power, escorts=escorts, stars=5)


def _cat(
    name: str,
    troop: str,
    widget: str,
    kind: str,
    value: float,
    *,
    arena_role: str | None = None,
    arena_value: float | None = None,
    arena_tags: tuple[str, ...] = (),
) -> CatalogEntry:
    applies = "widget" if "rally" in kind or "defender" in kind else "expedition"
    return CatalogEntry(
        name=name,
        troop=troop,
        widget_type=widget,
        effects=(EffectTag(kind, value, applies),),
        arena_role=arena_role,
        arena_value=arena_value,
        arena_tags=arena_tags,
    )


def test_recommend_includes_explain_and_leave_one_out() -> None:
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
    }
    result = recommend(heroes, catalog, troops, scenarios, force_mode="garrison")
    assert len(result.heroes) == 3
    for row in result.heroes:
        assert "explain" in row
        explain = row["explain"]
        assert isinstance(explain["fits_because"], list)
        assert explain["fits_because"]
        loo = explain["leave_one_out"]
        assert "marginal_points" in loo
        assert "baseline_points" in loo
        assert loo["status"] in {"Optimal", "Infeasible"}


def test_arena_includes_explain_and_leave_one_out() -> None:
    heroes = [
        HeroRecord(name="Helga", stars=1, power=170000),
        HeroRecord(name="Howard", stars=3, power=390000),
        HeroRecord(name="Jabel", stars=3, power=560000),
        HeroRecord(name="Chenko", stars=3, power=330000),
        HeroRecord(name="Saul", stars=2, power=240000),
        HeroRecord(name="Diana", stars=3, power=450000),
        HeroRecord(name="Gordon", stars=2, power=230000),
    ]
    catalog = {
        "Helga": _cat(
            "Helga", "infantry", "attack", "rally_attack", 15,
            arena_role="front_fighter", arena_value=90, arena_tags=("tank", "cc"),
        ),
        "Howard": _cat(
            "Howard", "infantry", "none", "damage_taken_down", 20,
            arena_role="front_tank", arena_value=85, arena_tags=("tank",),
        ),
        "Jabel": _cat(
            "Jabel", "cavalry", "attack", "rally_attack", 15,
            arena_role="back_cc", arena_value=92, arena_tags=("cc", "aoe"),
        ),
        "Chenko": _cat(
            "Chenko", "cavalry", "none", "attack_up", 15,
            arena_role="back_dps", arena_value=88, arena_tags=("dps", "aoe"),
        ),
        "Saul": _cat(
            "Saul", "archer", "none", "attack_up", 15,
            arena_role="back_cc", arena_value=80, arena_tags=("cc",),
        ),
        "Diana": _cat(
            "Diana", "archer", "none", "attack_up", 15,
            arena_role="back_dps", arena_value=70, arena_tags=("dps",),
        ),
        "Gordon": _cat(
            "Gordon", "cavalry", "none", "defense_up", 25,
            arena_role="back_support", arena_value=75, arena_tags=("heal",),
        ),
    }
    roles = load_arena_roles("config/arena_roles.yaml", catalog=catalog)
    result = optimize_arena_attack(heroes, catalog, roles)
    assert result.status == "Optimal"
    assert result.explanations
    for name in result.heroes:
        exp = result.explanations[name]
        assert exp["fits_because"]
        assert "leave_one_out" in exp
        assert exp["slot"] in {"F1", "F2", "B1", "B2", "B3"}
