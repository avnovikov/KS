"""Gear XP utility inherits governor via child recommend (OG-06)."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.spend_xp import build_event_utility

ROOT = Path(__file__).resolve().parents[1]


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


def test_gear_xp_swordland_utility_rises_with_governor() -> None:
    heroes = [
        HeroRecord(name="A", power=200_000, troop_type="infantry", stars=4, escorts=2000),
        HeroRecord(name="B", power=200_000, troop_type="cavalry", stars=4, escorts=2000),
        HeroRecord(name="C", power=200_000, troop_type="archers", stars=4, escorts=2000),
        HeroRecord(name="D", power=150_000, troop_type="infantry", stars=3, escorts=1000),
        HeroRecord(name="E", power=150_000, troop_type="cavalry", stars=3, escorts=1000),
    ]
    # Ensure catalog entries exist by using names from catalog
    from ks.heroes.optimize.catalog import load_catalog

    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    # Pick three real catalog heroes with distinct troops when possible
    picks: list[HeroRecord] = []
    for name, entry in catalog.items():
        if entry.troop in {"infantry", "cavalry", "archers"} or entry.troop == "archer":
            picks.append(
                HeroRecord(
                    name=name,
                    power=200_000,
                    troop_type=entry.troop or "infantry",
                    stars=4,
                    escorts=2000,
                )
            )
        if len(picks) >= 5:
            break
    assert len(picks) >= 3

    u0 = build_event_utility(
        "swordland", picks, config_root=ROOT, mode="solo", governor=None
    )
    u1 = build_event_utility(
        "swordland", picks, config_root=ROOT, mode="solo", governor=_gov(80.0)
    )
    base_u, _ = u0([])
    buff_u, _ = u1([])
    assert buff_u > base_u
