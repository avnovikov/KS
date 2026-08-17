"""PvP survival fill: infantry wall from β√C, then √n leftover."""

import math
from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.formation_mix import fill_after_floors, survival_floors
from ks.heroes.optimize.model import solve_mode
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.scenarios import load_scenarios, scenario_from_dict
from ks.heroes.optimize.types import CatalogEntry, EffectTag, Scenario, SurvivalFill, TroopsConfig

# β = 0.5 * √80280 so a typical 80k march still wants ~50% infantry.
REF_CAPACITY = 80_280
RALLY = SurvivalFill(
    infantry_beta=0.5 * math.sqrt(REF_CAPACITY),
    infantry_max_frac=0.6,
    min_type_frac=0.05,
)

LIVE_LIKE = TroopsConfig(
    infantry=39_294,
    cavalry=36_997,
    archers=48_123,
    march_capacity=REF_CAPACITY,
)

PLENTY = TroopsConfig(
    infantry=120_000,
    cavalry=120_000,
    archers=120_000,
    march_capacity=REF_CAPACITY,
)


def _cat(name: str, troop: str, widget: str, strength_effect: float) -> CatalogEntry:
    return CatalogEntry(
        name=name,
        troop=troop,
        widget_type=widget,
        effects=(EffectTag("attack_up", strength_effect, "expedition"),),
    )


def _three_type_roster() -> tuple[list[HeroRecord], dict[str, CatalogEntry]]:
    heroes = [
        HeroRecord(name="Helga", escorts=0, stars=5, power=2000),
        HeroRecord(name="Diana", escorts=0, stars=5, power=1800),
        HeroRecord(name="Chenko", escorts=0, stars=5, power=1700),
    ]
    catalog = {
        "Helga": _cat("Helga", "infantry", "attack", 50),
        "Diana": _cat("Diana", "cavalry", "none", 40),
        "Chenko": _cat("Chenko", "archer", "none", 45),
    }
    return heroes, catalog


def test_survival_infantry_floor_matches_half_at_reference_capacity() -> None:
    owned = {"infantry": 80_000, "cavalry": 80_000, "archers": 80_000}
    floors = survival_floors(owned, REF_CAPACITY, RALLY)
    assert floors["infantry"] == pytest.approx(0.5 * REF_CAPACITY, rel=0.01)
    assert floors["cavalry"] == pytest.approx(0.05 * REF_CAPACITY, rel=0.02)
    assert floors["archers"] == pytest.approx(0.05 * REF_CAPACITY, rel=0.02)
    assert sum(floors.values()) <= REF_CAPACITY


def test_survival_infantry_fraction_falls_on_larger_marches() -> None:
    owned = {"infantry": 200_000, "cavalry": 200_000, "archers": 200_000}
    big = 120_000
    floors = survival_floors(owned, big, RALLY)
    assert floors["infantry"] / big < 0.45
    assert floors["infantry"] / big > 0.35


def test_survival_floors_cap_infantry_at_owned() -> None:
    owned = {"infantry": 1_000, "cavalry": 40_000, "archers": 50_000}
    floors = survival_floors(owned, REF_CAPACITY, RALLY)
    assert floors["infantry"] == 1_000
    assert floors["cavalry"] > 0
    assert floors["archers"] > 0


def test_survival_fill_rejects_bad_policy() -> None:
    owned = {"infantry": 10, "cavalry": 10, "archers": 10}
    with pytest.raises(ValueError, match="beta"):
        survival_floors(owned, 30, SurvivalFill(infantry_beta=-1.0))
    with pytest.raises(ValueError, match="min_type_frac"):
        survival_floors(owned, 30, SurvivalFill(infantry_beta=1.0, min_type_frac=1.5))


def test_sqrt_leftover_balances_marginal_attractiveness() -> None:
    """Leftover raises a_k / √t_k until types other than the wall match."""
    owned = {"infantry": 80_000, "cavalry": 80_000, "archers": 80_000}
    attract = {"infantry": 0.3, "cavalry": 0.6, "archers": 1.3}
    floors = survival_floors(owned, REF_CAPACITY, RALLY)
    filled = fill_after_floors(owned, REF_CAPACITY, floors, attract)
    assert filled["infantry"] == floors["infantry"]
    assert filled["cavalry"] > floors["cavalry"]
    assert filled["archers"] > filled["cavalry"]
    assert sum(filled.values()) == REF_CAPACITY
    cav_rank = attract["cavalry"] / math.sqrt(filled["cavalry"])
    arch_rank = attract["archers"] / math.sqrt(filled["archers"])
    assert cav_rank == pytest.approx(arch_rank, rel=0.08)


def test_scenario_from_dict_loads_survival_fill() -> None:
    scenario = scenario_from_dict(
        "rally_lead",
        {
            "combat_rate": 80,
            "survival_fill": {
                "infantry_beta": 141.67,
                "infantry_max_frac": 0.6,
                "min_type_frac": 0.05,
            },
        },
    )
    assert scenario.survival_fill is not None
    assert scenario.survival_fill.infantry_beta == pytest.approx(141.67)
    assert scenario.survival_fill.min_type_frac == pytest.approx(0.05)


def test_rally_lead_keeps_infantry_wall_without_locking_20_percent_cavalry() -> None:
    heroes, catalog = _three_type_roster()
    scenario = Scenario(
        mode="rally_lead",
        combat_rate=80,
        enemy_power_scale=150_000,
        require_widget="attack",
        formation_weights={"infantry": 0.3, "cavalry": 0.6, "archers": 1.3},
        survival_fill=RALLY,
    )
    sol = solve_mode(heroes, catalog, PLENTY, scenario)
    assert sol.status == "Optimal"
    total = sum(sol.troops.values())
    assert total > 0
    assert sol.troops["infantry"] / total == pytest.approx(0.5, rel=0.03)
    assert 0.05 <= sol.troops["cavalry"] / total < 0.12
    assert sol.troops["archers"] / total > 0.35


def test_rally_lead_uses_all_infantry_when_short_of_survival_floor() -> None:
    heroes, catalog = _three_type_roster()
    troops = TroopsConfig(
        infantry=1_000,
        cavalry=40_000,
        archers=50_000,
        march_capacity=REF_CAPACITY,
    )
    scenario = Scenario(
        mode="rally_lead",
        combat_rate=80,
        enemy_power_scale=150_000,
        require_widget="attack",
        formation_weights={"infantry": 0.3, "cavalry": 0.6, "archers": 1.3},
        survival_fill=RALLY,
    )
    sol = solve_mode(heroes, catalog, troops, scenario)
    assert sol.status == "Optimal"
    assert sol.troops["infantry"] == 1_000
    assert sol.troops["cavalry"] > 0
    assert sol.troops["archers"] > 0


def test_recommend_swordland_yaml_keeps_rally_lead_infantry_wall() -> None:
    heroes, catalog = _three_type_roster()
    root = Path(__file__).resolve().parents[1]
    scenarios = load_scenarios(root / "config" / "point_scenarios.yaml")
    result = recommend(
        heroes, catalog, LIVE_LIKE, scenarios, force_mode="rally_lead"
    )
    assert result.recommended_mode == "rally_lead"
    total = sum(result.troops.values())
    assert total > 0
    assert result.troops["infantry"] / total >= 0.45
    assert result.troops["cavalry"] / total < 0.12
