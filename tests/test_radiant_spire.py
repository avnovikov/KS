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
    )
    assert boosted.lineup_score > base.lineup_score


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
        },
        squad=TroopResearchRow(attack_pct=10.0),
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
        base.marches[0].breakdown["atk_pct"]["infantry"] + 40.0
    )
    assert boosted.marches[0].breakdown["atk_pct"]["cavalry"] == pytest.approx(
        base.marches[0].breakdown["atk_pct"]["cavalry"] + 10.0
    )
    assert boosted.research is not None
    assert boosted.research["troops"]["infantry"]["attack_pct"] == pytest.approx(30.0)
    assert boosted.research["squad"]["attack_pct"] == pytest.approx(10.0)


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
    )
    assert len(result.marches) == 3
    assert len({h for m in result.marches for h in m.hero_names}) == 9
