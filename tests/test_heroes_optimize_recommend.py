from ks.heroes.models import HeroRecord
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.types import CatalogEntry, EffectTag, Scenario, TroopsConfig


def _hero(name: str, *, power: int = 1000, escorts: int = 5) -> HeroRecord:
    return HeroRecord(name=name, power=power, escorts=escorts, stars=5)


def _cat(name: str, troop: str, widget: str, kind: str, value: float) -> CatalogEntry:
    return CatalogEntry(
        name=name,
        troop=troop,
        widget_type=widget,
        effects=(EffectTag(kind, value, "widget" if "rally" in kind or "defender" in kind else "expedition"),),
    )


def test_recommend_picks_garrison_for_defense_roster() -> None:
    heroes = [
        _hero("Zoe"),
        _hero("Saul"),
        _hero("Howard"),
        _hero("WeakAttack", power=10),
    ]
    catalog = {
        "Zoe": _cat("Zoe", "infantry", "defense", "defender_attack", 30),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 20),
        "Howard": _cat("Howard", "cavalry", "none", "damage_taken_down", 20),
        "WeakAttack": _cat("WeakAttack", "infantry", "attack", "rally_attack", 1),
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
    }
    result = recommend(heroes, catalog, troops, scenarios)
    assert result.recommended_mode == "garrison"
    assert result.expected_personal_points > 0
    assert len(result.heroes) == 3


def test_recommend_force_mode() -> None:
    heroes = [_hero("Zoe"), _hero("Saul"), _hero("Howard"), _hero("Amadeus")]
    catalog = {
        "Zoe": _cat("Zoe", "infantry", "defense", "defender_attack", 30),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 20),
        "Howard": _cat("Howard", "cavalry", "none", "damage_taken_down", 20),
        "Amadeus": _cat("Amadeus", "infantry", "attack", "rally_attack", 30),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=50,
            personal_rate=600,
            require_widget="defense",
            enemy_power_scale=50000,
            formation_weights={"infantry": 1.0, "cavalry": 1.0, "archers": 1.0},
        ),
        "rally_lead": Scenario(
            mode="rally_lead",
            combat_rate=80,
            require_widget="attack",
            enemy_power_scale=50000,
            formation_weights={"infantry": 1.0, "cavalry": 1.0, "archers": 1.0},
        ),
    }
    result = recommend(heroes, catalog, troops, scenarios, force_mode="rally_lead")
    assert result.recommended_mode == "rally_lead"
