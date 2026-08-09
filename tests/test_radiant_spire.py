"""Radiant Spire dual-march proxy optimiser tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.radiant_spire import (
    PROXY_BANNER,
    counts_for_ratio,
    optimize_radiant,
    ratio_candidates,
    score_march,
)
from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats
from ks.heroes.optimize.types import TroopsConfig

ROOT = Path(__file__).resolve().parents[1]


def _unit(atk: float = 100.0, defense: float = 10.0, leth: float = 10.0, hp: float = 300.0) -> TroopUnitStats:
    return TroopUnitStats(attack=atk, defense=defense, lethality=leth, health=hp)


def _table() -> TroopStatsTable:
    u = _unit()
    return TroopStatsTable(
        source="test",
        default_truegold=0,
        stats={
            typ: {6: {0: u}}
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


def test_ratio_candidates_include_seed_and_normalize() -> None:
    cands = ratio_candidates()
    assert any(
        abs(r["infantry"] - 0.50) < 1e-9
        and abs(r["cavalry"] - 0.15) < 1e-9
        and abs(r["archers"] - 0.35) < 1e-9
        for r in cands
    )
    for r in cands:
        assert abs(sum(r.values()) - 1.0) < 1e-9
        assert all(v >= 0 for v in r.values())


def test_counts_for_ratio_sum_to_capacity() -> None:
    counts = counts_for_ratio(
        {"infantry": 0.5, "cavalry": 0.15, "archers": 0.35},
        capacity=1000,
        owned={"infantry": 10_000, "cavalry": 10_000, "archers": 10_000},
    )
    assert sum(counts.values()) == 1000
    assert counts["infantry"] == 500
    assert counts["cavalry"] == 150
    assert counts["archers"] == 350


def test_score_march_rises_with_attack_pct() -> None:
    counts = {"infantry": 500, "cavalry": 150, "archers": 350}
    units = {t: _unit() for t in counts}
    low = score_march(
        counts,
        units,
        atk_pct={t: 0.0 for t in counts},
        def_pct={t: 0.0 for t in counts},
        leth_pct={t: 0.0 for t in counts},
        hp_pct={t: 0.0 for t in counts},
    )
    high = score_march(
        counts,
        units,
        atk_pct={t: 50.0 for t in counts},
        def_pct={t: 0.0 for t in counts},
        leth_pct={t: 0.0 for t in counts},
        hp_pct={t: 0.0 for t in counts},
    )
    assert high.score > low.score


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


def test_optimize_radiant_exclusive_heroes_and_governor_shift() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    # Catalog troops: infantry / cavalry / archers — two exclusive marches.
    names = [
        ("Helga", "infantry"),
        ("Jabel", "cavalry"),
        ("Diana", "archers"),
        ("Howard", "infantry"),
        ("Chenko", "cavalry"),
        ("Quinn", "archers"),
    ]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")

    heroes = [_hero(n, t, power=2_000_000 - i * 50_000) for i, (n, t) in enumerate(names)]
    troops = TroopsConfig(
        infantry=50_000,
        cavalry=50_000,
        archers=50_000,
        march_capacity=100_000,
        infantry_levels=((6, 50_000),),
        cavalry_levels=((6, 50_000),),
        archers_levels=((6, 50_000),),
    )
    base = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=0.0, defense=0.0),
        troops=troops,
        troop_stats=_table(),
        active_marches=2,
        event_march_capacity=None,
    )
    assert len(base.marches) == 2
    used = [h for m in base.marches for h in m.hero_names]
    assert len(used) == len(set(used))
    assert base.proxy_banner == PROXY_BANNER
    assert base.lineup_score == pytest.approx(
        sum(m.score for m in base.marches)
    )

    boosted = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(atk=80.0, defense=40.0),
        troops=troops,
        troop_stats=_table(),
        active_marches=2,
        event_march_capacity=None,
    )
    assert boosted.lineup_score > base.lineup_score
    assert base.opponent is None

    with_floor = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=2,
        floor=10,
        event_march_capacity=None,
    )
    assert with_floor.opponent is not None
    assert len(with_floor.opponent["marches"]) == 2
    opp0 = with_floor.opponent["marches"][0]
    assert opp0["hero_names"] == ["AI", "AI", "AI"]
    assert abs(opp0["ratio"]["infantry"] - 0.53) < 1e-9
    assert sum(opp0["counts"].values()) == sum(with_floor.marches[0].counts.values())
    assert "attack_pct" in opp0["bonuses"]["infantry"]

    overridden = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=2,
        floor=10,
        event_march_capacity=None,
        enemy_ratio={"infantry": 0.70, "cavalry": 0.20, "archers": 0.10},
        enemy_bonuses={
            "infantry": {
                "attack_pct": 111,
                "defense_pct": 0,
                "lethality_pct": 0,
                "health_pct": 0,
            }
        },
    )
    assert abs(overridden.opponent["marches"][0]["ratio"]["infantry"] - 0.70) < 1e-9
    assert overridden.opponent["marches"][0]["bonuses"]["infantry"]["attack_pct"] == 111.0
    assert overridden.floor.get("overrides_applied") is True


def test_optimize_radiant_includes_research_pct() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [
        ("Helga", "infantry"),
        ("Jabel", "cavalry"),
        ("Diana", "archers"),
        ("Howard", "infantry"),
        ("Chenko", "cavalry"),
        ("Quinn", "archers"),
    ]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")

    from ks.heroes.research_models import ResearchBonuses, TroopResearchRow

    heroes = [_hero(n, t, power=3_000_000 - i * 10_000) for i, (n, t) in enumerate(names)]
    troops = TroopsConfig(
        infantry=90_000,
        cavalry=90_000,
        archers=90_000,
        march_capacity=80_000,
        infantry_levels=((6, 90_000),),
        cavalry_levels=((6, 90_000),),
        archers_levels=((6, 90_000),),
    )
    research = ResearchBonuses(
        troops={
            "infantry": TroopResearchRow(attack_pct=30.0, lethality_pct=5.0),
            "cavalry": TroopResearchRow(),
            "archers": TroopResearchRow(),
        }
    )
    base = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=1,
    )
    boosted = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        research=research,
        active_marches=1,
    )
    assert boosted.lineup_score > base.lineup_score
    assert boosted.marches[0].breakdown["atk_pct"]["infantry"] == pytest.approx(
        base.marches[0].breakdown["atk_pct"]["infantry"] + 30.0
    )
    assert boosted.research is not None
    assert boosted.research["troops"]["infantry"]["attack_pct"] == pytest.approx(30.0)


def test_optimize_radiant_uses_event_march_capacity_not_inventory() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [
        ("Helga", "infantry"),
        ("Jabel", "cavalry"),
        ("Diana", "archers"),
        ("Howard", "infantry"),
        ("Chenko", "cavalry"),
        ("Quinn", "archers"),
    ]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")
    heroes = [_hero(n, t, power=2_000_000 - i * 50_000) for i, (n, t) in enumerate(names)]
    # Inventory capacity deliberately small — event fill must ignore it.
    troops = TroopsConfig(
        infantry=10_000,
        cavalry=10_000,
        archers=10_000,
        march_capacity=20_000,
        infantry_levels=((6, 10_000),),
        cavalry_levels=((6, 10_000),),
        archers_levels=((6, 10_000),),
    )
    result = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=2,
        event_march_capacity=150_000,
    )
    assert len(result.marches) == 2
    for march in result.marches:
        assert march.capacity == 150_000
        assert sum(march.counts.values()) == 150_000


def test_optimize_radiant_schema_allows_three_marches() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    names = [
        ("Helga", "infantry"),
        ("Jabel", "cavalry"),
        ("Diana", "archers"),
        ("Howard", "infantry"),
        ("Chenko", "cavalry"),
        ("Quinn", "archers"),
        ("Forrest", "infantry"),
        ("Gordon", "cavalry"),
        ("Saul", "archers"),
    ]
    missing = [n for n, _ in names if n not in catalog]
    if missing:
        pytest.skip(f"catalog missing fixtures: {missing}")

    heroes = [_hero(n, t, power=3_000_000 - i * 10_000) for i, (n, t) in enumerate(names)]
    troops = TroopsConfig(
        infantry=90_000,
        cavalry=90_000,
        archers=90_000,
        march_capacity=80_000,
        infantry_levels=((6, 90_000),),
        cavalry_levels=((6, 90_000),),
        archers_levels=((6, 90_000),),
    )
    result = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=3,
        event_march_capacity=None,
    )
    assert len(result.marches) == 3
    assert len({h for m in result.marches for h in m.hero_names}) == 9


def test_optimize_radiant_saved_opponents_use_enemy_proxy() -> None:
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
    heroes = [_hero(n, t, power=3_000_000 - i * 10_000) for i, (n, t) in enumerate(names)]
    troops = TroopsConfig(
        infantry=90_000,
        cavalry=90_000,
        archers=90_000,
        march_capacity=80_000,
        infantry_levels=((6, 90_000),),
        cavalry_levels=((6, 90_000),),
        archers_levels=((6, 90_000),),
    )
    saved = [
        {
            "hero_names": ["Helga", "Jabel", "Diana"],
            "hero_level": 80,
            "gear_enhancement": 20,
            "levels": {"infantry": 6, "cavalry": 6, "archers": 6},
            "counts": {"infantry": 40000, "cavalry": 40000, "archers": 40000},
            "bonuses": {
                t: {
                    "attack_pct": 0.0,
                    "defense_pct": 0.0,
                    "lethality_pct": 0.0,
                    "health_pct": 0.0,
                }
                for t in ("infantry", "cavalry", "archers")
            },
        }
    ]
    stubbed = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=1,
        floor=10,
        event_march_capacity=150_000,
    )
    proxied = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=1,
        floor=10,
        event_march_capacity=150_000,
        saved_opponents=saved,
    )
    assert proxied.floor is not None
    assert proxied.floor.get("enemy_proxy") is True
    mc_stub = stubbed.marches[0].breakdown["mc"]
    mc_proxy = proxied.marches[0].breakdown["mc"]
    assert mc_proxy["enemy_score"] != pytest.approx(mc_stub["enemy_score"])


def test_optimize_radiant_keeps_cavalry_troops_with_cav_hero() -> None:
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
    heroes = [_hero(n, t, power=3_000_000 - i * 10_000) for i, (n, t) in enumerate(names)]
    troops = TroopsConfig(
        infantry=90_000,
        cavalry=90_000,
        archers=90_000,
        march_capacity=80_000,
        infantry_levels=((6, 90_000),),
        cavalry_levels=((6, 90_000),),
        archers_levels=((6, 90_000),),
    )
    result = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=[],
        governor=_gov(),
        troops=troops,
        troop_stats=_table(),
        active_marches=2,
        floor=9,
        event_march_capacity=150_000,
    )
    assert result.engine == "mc"
    for march in result.marches:
        troops_in_lineup = {
            (march.breakdown.get("hero_shares") or {})
            .get("heroes", {})
            .get(name, {})
            .get("troop")
            for name in march.hero_names
        }
        if "cavalry" in troops_in_lineup:
            assert march.counts["cavalry"] > 0
            assert march.ratio["cavalry"] >= 0.05 - 1e-9
        assert march.breakdown.get("mc", {}).get("trials") == 32
