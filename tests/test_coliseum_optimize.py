"""Coliseum mystic-trial optimiser — heroes/gear primary, governor off by default."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.mystic_trial.coliseum import optimize_coliseum
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
        stats={
            typ: {tier: {0: u} for tier in range(1, 12)}
            for typ in ("infantry", "cavalry", "archers")
        },
    )


def _gov(*, atk: float = 0.0, defense: float = 0.0) -> GovernorTroopBonuses:
    return GovernorTroopBonuses(
        attack_pct={t: atk for t in ("infantry", "cavalry", "archers")},
        defense_pct={t: defense for t in ("infantry", "cavalry", "archers")},
        set_attack_pct=0.0,
        set_defense_pct=0.0,
        set_tier=None,
    )


def _hero(
    name: str,
    troop: str,
    *,
    power: int = 1_000_000,
    attack: float = 10.0,
    lethality: float = 5.0,
) -> HeroRecord:
    prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}[troop]
    return HeroRecord(
        name=name,
        power=power,
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
                f"{prefix} Lethality": lethality,
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


def _fixture_heroes() -> list[HeroRecord]:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [
        ("Helga", "infantry"),
        ("Jabel", "cavalry"),
        ("Diana", "archers"),
    ]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")
    return [_hero(n, t, attack=20.0) for n, t in names]


def test_higher_hero_expedition_attack_raises_coliseum_score() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    base_heroes = _fixture_heroes()
    boosted_heroes = [
        _hero(h.name, h.troop_type or "infantry", attack=80.0) for h in base_heroes
    ]
    troops = _troops()
    base = optimize_coliseum(
        base_heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=0.0),
        troops=troops,
        troop_stats=_table(),
    )
    boosted = optimize_coliseum(
        boosted_heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=0.0),
        troops=troops,
        troop_stats=_table(),
    )
    assert boosted.lineup_score > base.lineup_score
    assert base.active_marches >= 1
    assert len([m for m in base.to_dict()["marches"] if m]) >= 1
    assert base.proxy_banner == PROXY_BANNER or PROXY_BANNER in base.proxy_banner
    assert base.engine == "proxy"
    assert base.to_dict()["room"] == "coliseum"
    assert base.schema_marches == 2


def test_coliseum_fills_two_marches_with_six_heroes() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [
        ("Helga", "infantry"),
        ("Howard", "infantry"),
        ("Jabel", "cavalry"),
        ("Chenko", "cavalry"),
        ("Diana", "archers"),
        ("Saul", "archers"),
    ]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")
    heroes = [_hero(n, t, attack=20.0 + i) for i, (n, t) in enumerate(names)]
    result = optimize_coliseum(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=0.0),
        troops=_troops(),
        troop_stats=_table(),
    )
    filled = [m for m in result.to_dict()["marches"] if m]
    assert len(filled) == 2
    assert result.active_marches == 2
    names0 = set(filled[0]["hero_names"])
    names1 = set(filled[1]["hero_names"])
    assert names0.isdisjoint(names1)


def test_coliseum_reuses_same_faceplate_on_both_marches() -> None:
    """Coliseum marches use fungible class sets — one Inf helmet equips both."""
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [
        ("Helga", "infantry"),
        ("Howard", "infantry"),
        ("Jabel", "cavalry"),
        ("Chenko", "cavalry"),
        ("Diana", "archers"),
        ("Quinn", "archers"),
    ]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")
    heroes = [_hero(n, t, attack=20.0 + i) for i, (n, t) in enumerate(names)]
    faceplate = GearRecord(
        piece_id="fp-shared",
        name="Judicator Faceplate",
        troop_type="infantry",
        slot="helmet",
        rarity="mythic",
        enhancement_level=5,
        mastery_level=0,
        power=500_000,
    )
    result = optimize_coliseum(
        heroes,
        catalog,
        gear_pieces=[faceplate],
        governor=_gov(atk=0.0),
        troops=_troops(),
        troop_stats=_table(),
        player_event_troops={"tier": 10, "march_size": 250_000},
    )
    filled = [m for m in result.to_dict()["marches"] if m]
    assert len(filled) == 2
    inf_ids: list[str] = []
    for march in filled:
        for name in march["hero_names"]:
            troop = catalog[name].troop
            if troop != "infantry":
                continue
            pieces = (march.get("gear_assignment") or {}).get(name) or []
            ids = [p.get("piece_id") for p in pieces if p.get("piece_id")]
            assert "fp-shared" in ids, f"{name} missing shared faceplate"
            inf_ids.extend(ids)
    assert inf_ids.count("fp-shared") == 2


def test_coliseum_uses_player_event_troops_not_inventory_mix() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    heroes = _fixture_heroes()
    # Tiny inventory — event troops must ignore it.
    troops = TroopsConfig(
        infantry=100,
        cavalry=100,
        archers=100,
        march_capacity=500,
        infantry_levels=((6, 100),),
        cavalry_levels=((6, 100),),
        archers_levels=((6, 100),),
    )
    result = optimize_coliseum(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=0.0),
        troops=troops,
        troop_stats=_table(),
        player_event_troops={"tier": 10, "march_size": 250_000},
    )
    filled = [m for m in result.to_dict()["marches"] if m]
    assert filled
    for march in filled:
        assert march["capacity"] == 250_000
        assert sum(march["counts"].values()) == 250_000


def test_governor_atk_alone_does_not_raise_coliseum_score_by_default() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    heroes = _fixture_heroes()
    troops = _troops()
    base = optimize_coliseum(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=0.0),
        troops=troops,
        troop_stats=_table(),
    )
    with_gov = optimize_coliseum(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=200.0, defense=100.0),
        troops=troops,
        troop_stats=_table(),
    )
    assert with_gov.lineup_score == pytest.approx(base.lineup_score)
