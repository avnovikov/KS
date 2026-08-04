from ks.heroes.models import HeroRecord, SkillRecord
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


def test_troop_bonus_scales_with_deployed_troop_count() -> None:
    """A hero's own troop-percentage bonus (Attack/Lethality from skills or
    gear) must multiply the troops actually marching with them, not just add
    a flat, troop-count-blind nudge to that hero's own pick score — the same
    50% ought to be worth far more marching a million troops than a
    thousand. Each run forces exactly one infantry candidate (no selection
    ambiguity) so the comparison isolates the troop-count-scaled term."""

    def _infantry(name: str, *, bonus: bool) -> HeroRecord:
        skills = ()
        if bonus:
            skills = (
                SkillRecord(slot=2, upgrade_preview="Attack Up: 50%", current_bonus=50.0),
            )
        return HeroRecord(name=name, escorts=0, stars=3, power=100_000, skills=skills)

    def _cat(name: str, troop: str) -> CatalogEntry:
        return CatalogEntry(name=name, troop=troop, widget_type="none", effects=())

    def _points(troops_n: int, *, bonus: bool) -> tuple[float, int]:
        infantry_name = "Bonus" if bonus else "NoBonus"
        cavalry = HeroRecord(name="Cav", escorts=0, stars=3, power=100_000)
        archer = HeroRecord(name="Arc", escorts=0, stars=3, power=100_000)
        catalog = {
            infantry_name: _cat(infantry_name, "infantry"),
            "Cav": _cat("Cav", "cavalry"),
            "Arc": _cat("Arc", "archer"),
        }
        troops = TroopsConfig(
            infantry=troops_n, cavalry=10, archers=10, march_capacity=troops_n + 50
        )
        scenario = Scenario(
            mode="rally_lead",
            combat_rate=100,
            enemy_power_scale=100_000,
            formation_weights={"infantry": 1.0, "cavalry": 1.0, "archers": 1.0},
        )
        sol = solve_mode(
            [_infantry(infantry_name, bonus=bonus), cavalry, archer],
            catalog,
            troops,
            scenario,
        )
        assert sol.status == "Optimal"
        return sol.expected_personal_points, sol.troops["infantry"]

    def _delta(troops_n: int) -> float:
        points_no_bonus, deployed_no_bonus = _points(troops_n, bonus=False)
        points_bonus, deployed_bonus = _points(troops_n, bonus=True)
        assert deployed_no_bonus == troops_n
        assert deployed_bonus == troops_n
        return points_bonus - points_no_bonus

    delta_small = _delta(1_000)
    delta_huge = _delta(1_000_000)
    assert delta_small > 0
    assert delta_huge > delta_small * 100  # scales roughly 1000x; generous margin
