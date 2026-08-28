"""Governor troop bonuses in Swordland ILP scoring (OG-04)."""

from __future__ import annotations

from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.model import solve_mode
from ks.heroes.optimize.types import (
    CatalogEntry,
    EventProfile,
    Scenario,
    TroopsConfig,
)


def _gov(cavalry_atk: float) -> GovernorTroopBonuses:
    return GovernorTroopBonuses(
        attack_pct={
            "infantry": 0.0,
            "cavalry": cavalry_atk,
            "archers": 0.0,
        },
        defense_pct={"infantry": 0.0, "cavalry": 0.0, "archers": 0.0},
        set_attack_pct=0.0,
        set_defense_pct=0.0,
        set_tier=None,
    )


def _scenario() -> Scenario:
    return Scenario(
        mode="field",
        combat_rate=1000.0,
        minutes_held=0.0,
        personal_rate=0.0,
        p_first=0.0,
        first_bonus=0.0,
        loot_expected=0.0,
        enemy_power_scale=1.0,
        formation_weights={"infantry": 0.5, "cavalry": 0.2, "archers": 0.3},
        require_widget=None,
    )


def test_swordland_score_rises_with_governor_cavalry_attack() -> None:
    heroes = [
        HeroRecord(name="A", power=100_000, troop_type="infantry", stars=3, escorts=1000),
        HeroRecord(name="B", power=100_000, troop_type="cavalry", stars=3, escorts=1000),
        HeroRecord(name="C", power=100_000, troop_type="archers", stars=3, escorts=1000),
    ]
    catalog = {
        "A": CatalogEntry(name="A", troop="infantry", rarity="epic"),
        "B": CatalogEntry(name="B", troop="cavalry", rarity="epic"),
        "C": CatalogEntry(name="C", troop="archers", rarity="epic"),
    }
    troops = TroopsConfig(infantry=5000, cavalry=5000, archers=5000, march_capacity=10_000)
    event = EventProfile(name="swordland")
    base = solve_mode(
        heroes, catalog, troops, _scenario(), event=event, governor=None
    )
    buffed = solve_mode(
        heroes, catalog, troops, _scenario(), event=event, governor=_gov(80.0)
    )
    assert buffed.status == "Optimal"
    assert buffed.expected_personal_points > base.expected_personal_points
