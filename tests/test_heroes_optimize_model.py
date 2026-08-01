from ks.heroes.models import HeroRecord
from ks.heroes.optimize.model import solve_mode
from ks.heroes.optimize.types import CatalogEntry, EffectTag, Scenario, TroopsConfig


def _cat(name: str, troop: str, widget: str, strength_effect: float) -> CatalogEntry:
    return CatalogEntry(
        name=name,
        troop=troop,
        widget_type=widget,
        effects=(EffectTag("attack_up", strength_effect, "expedition"),),
    )


def test_solve_mode_respects_capacity_and_ownership() -> None:
    heroes = [
        HeroRecord(name="A", escorts=10, stars=5, power=1000),
        HeroRecord(name="B", escorts=10, stars=5, power=1000),
        HeroRecord(name="C", escorts=10, stars=5, power=1000),
        HeroRecord(name="D", escorts=10, stars=5, power=100),
        HeroRecord(name="E", escorts=10, stars=5, power=100),
        HeroRecord(name="F", escorts=10, stars=5, power=100),
    ]
    catalog = {
        "A": _cat("A", "infantry", "defense", 50),
        "B": _cat("B", "cavalry", "defense", 40),
        "C": _cat("C", "archer", "defense", 30),
        "D": _cat("D", "infantry", "defense", 5),
        "E": _cat("E", "cavalry", "defense", 5),
        "F": _cat("F", "archer", "defense", 5),
    }
    troops = TroopsConfig(infantry=60, cavalry=20, archers=20, march_capacity=100)
    scenario = Scenario(
        mode="garrison",
        combat_rate=40,
        minutes_held=10,
        personal_rate=100,
        enemy_power_scale=10_000,
        require_widget="defense",
        formation_weights={"infantry": 1.2, "cavalry": 0.6, "archers": 0.8},
    )
    sol = solve_mode(heroes, catalog, troops, scenario)
    assert sol.status == "Optimal"
    assert len(sol.hero_names) == 3
    assert set(sol.hero_names) == {"A", "B", "C"}
    total = sum(sol.troops.values())
    assert total <= sol.effective_capacity
    assert sol.troops["infantry"] <= 60
    assert sol.troops["cavalry"] <= 20
    assert sol.troops["archers"] <= 20
    assert sol.expected_personal_points > 0
