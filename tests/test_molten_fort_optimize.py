"""Molten Fort mystic-trial optimiser — governor-primary scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.mystic_trial.molten import optimize_molten
from ks.heroes.optimize.mystic_trial.proxy import PROXY_BANNER
from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats
from ks.heroes.optimize.types import TroopsConfig

ROOT = Path(__file__).resolve().parents[1]


def _unit(
    atk: float = 100.0, defense: float = 10.0, leth: float = 10.0, hp: float = 300.0
) -> TroopUnitStats:
    return TroopUnitStats(attack=atk, defense=defense, lethality=leth, health=hp)


def _table() -> TroopStatsTable:
    u = _unit()
    return TroopStatsTable(
        source="test",
        default_truegold=0,
        stats={typ: {6: {0: u}} for typ in ("infantry", "cavalry", "archers")},
    )


def _gov(
    *,
    infantry_atk: float = 0.0,
    cavalry_atk: float = 0.0,
    archers_atk: float = 0.0,
    defense: float = 0.0,
    set_attack_pct: float = 0.0,
    set_defense_pct: float = 0.0,
) -> GovernorTroopBonuses:
    return GovernorTroopBonuses(
        attack_pct={
            "infantry": infantry_atk,
            "cavalry": cavalry_atk,
            "archers": archers_atk,
        },
        defense_pct={t: defense for t in ("infantry", "cavalry", "archers")},
        set_attack_pct=set_attack_pct,
        set_defense_pct=set_defense_pct,
        set_tier="mythic" if set_attack_pct or set_defense_pct else None,
    )


def _hero(name: str, troop: str, *, attack: float = 10.0) -> HeroRecord:
    prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}[troop]
    return HeroRecord(
        name=name,
        power=1_000_000,
        troop_type=troop,
        rarity="legendary",
        stars=5,
        pellets=0,
        escorts=10_000,
        roster_page=0,
        roster_index=0,
        scraped_at="2026-08-09T00:00:00Z",
        stats=HeroStats(
            expedition={
                f"{prefix} Attack": attack,
                f"{prefix} Defense": 5.0,
                f"{prefix} Health": 5.0,
                f"{prefix} Lethality": 5.0,
            }
        ),
    )


def _troops() -> TroopsConfig:
    return TroopsConfig(
        infantry=50_000,
        cavalry=50_000,
        archers=50_000,
        march_capacity=100_000,
        infantry_levels=((6, 50_000),),
        cavalry_levels=((6, 50_000),),
        archers_levels=((6, 50_000),),
    )


def test_doubling_governor_archer_atk_raises_molten_score() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [("Helga", "infantry"), ("Jabel", "cavalry"), ("Diana", "archers")]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")
    heroes = [_hero(n, t) for n, t in names]
    troops = _troops()

    base = optimize_molten(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(archers_atk=40.0),
        troops=troops,
        troop_stats=_table(),
    )
    doubled = optimize_molten(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(archers_atk=80.0),
        troops=troops,
        troop_stats=_table(),
    )
    assert doubled.lineup_score > base.lineup_score
    assert base.active_marches == 1
    assert base.proxy_banner == PROXY_BANNER
    assert base.engine == "proxy"
    payload = base.to_dict()
    assert payload["room"] == "molten_fort"
    assert len([m for m in payload["marches"] if m]) == 1


def test_molten_does_not_double_count_set_attack_in_maps() -> None:
    """attack_pct already includes set bonuses from governor_troop_bonuses().

    Passing set_attack_pct separately must not raise the score above attack_pct alone.
    """
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [("Helga", "infantry"), ("Jabel", "cavalry"), ("Diana", "archers")]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")
    heroes = [_hero(n, t) for n, t in names]
    troops = _troops()

    # Maps already include the set bonus (as governor_troop_bonuses does).
    with_maps = optimize_molten(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(archers_atk=50.0, set_attack_pct=10.0),
        troops=troops,
        troop_stats=_table(),
    )
    maps_only = optimize_molten(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(archers_atk=50.0, set_attack_pct=0.0),
        troops=troops,
        troop_stats=_table(),
    )
    assert with_maps.lineup_score == pytest.approx(maps_only.lineup_score)
