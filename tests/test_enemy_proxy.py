"""Enemy march proxy scoring for Radiant opponent AI heroes."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.mystic_trial.combat_mc import simulate_floor
from ks.heroes.optimize.mystic_trial.enemy_proxy import (
    bonus_to_percent_points,
    mythic_set_for_troop,
    opponent_complete,
    score_enemy_march,
)
from ks.heroes.optimize.mystic_trial.floors import FloorStub, empty_enemy_bonuses
from ks.heroes.optimize.mystic_trial.proxy import MarchScore
from ks.heroes.optimize.troop_stats import load_troop_stats


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(None, REPO / "config" / "hero_catalog.yaml")


@pytest.fixture(scope="module")
def troop_stats():
    return load_troop_stats(REPO / "config" / "troop_stats.yaml")


def _complete_march(**overrides):
    base = {
        "hero_names": ["Helga", "Jabel", "Diana"],
        "hero_level": 80,
        "gear_enhancement": 20,
        "levels": {"infantry": 6, "cavalry": 6, "archers": 6},
        "counts": {"infantry": 50000, "cavalry": 50000, "archers": 50000},
        "bonuses": empty_enemy_bonuses(),
    }
    base.update(overrides)
    return base


def test_bonus_to_percent_points_passthrough() -> None:
    """Stored report values are percent-points; score_march uses 1 + pp/100.

    Enter 115 for +115% (×2.15), not a game 'total' 115% that we used to
    rewrite into +15.
    """
    assert bonus_to_percent_points(115.0) == pytest.approx(115.0)
    assert bonus_to_percent_points(33.0) == pytest.approx(33.0)
    assert bonus_to_percent_points(160.2) == pytest.approx(160.2)
    assert bonus_to_percent_points(0.0) == pytest.approx(0.0)
    assert bonus_to_percent_points(85) == pytest.approx(85.0)


def test_report_bonus_maps_match_stored_percent_points() -> None:
    from ks.heroes.optimize.mystic_trial.enemy_proxy import report_bonus_percent_maps

    atk, defense, leth, hp = report_bonus_percent_maps(
        {
            "infantry": {
                "attack_pct": 115.0,
                "defense_pct": 115.0,
                "lethality_pct": 33.0,
                "health_pct": 33.0,
            },
            "cavalry": {
                "attack_pct": 115.0,
                "defense_pct": 115.0,
                "lethality_pct": 33.0,
                "health_pct": 33.0,
            },
            "archers": {
                "attack_pct": 115.0,
                "defense_pct": 115.0,
                "lethality_pct": 33.0,
                "health_pct": 33.0,
            },
        }
    )
    assert atk["infantry"] == pytest.approx(115.0)
    assert defense["cavalry"] == pytest.approx(115.0)
    assert leth["archers"] == pytest.approx(33.0)
    assert hp["infantry"] == pytest.approx(33.0)


def test_mythic_set_four_slots() -> None:
    gear = mythic_set_for_troop("cavalry", enhancement=40)
    assert set(gear) == {"helmet", "chest", "gloves", "boots"}
    assert all(p.rarity == "mythic" for p in gear.values())
    assert all(p.enhancement_level == 40 for p in gear.values())


def test_opponent_complete_requires_heroes_and_mass() -> None:
    assert opponent_complete(_complete_march()) is True
    assert opponent_complete(_complete_march(hero_names=["Helga", "Jabel", ""])) is False
    assert opponent_complete(_complete_march(hero_level=None)) is False
    assert opponent_complete(
        _complete_march(counts={"infantry": 0, "cavalry": 0, "archers": 0})
    ) is False


def test_score_enemy_march_positive(catalog, troop_stats) -> None:
    scored = score_enemy_march(_complete_march(), catalog, troop_stats, truegold=0)
    assert scored.score > 0


def test_score_enemy_does_not_stack_report_on_heroes(catalog, troop_stats) -> None:
    """Battle-report bonuses are formation totals — not added on top of AI gear."""
    march = _complete_march(
        bonuses={
            t: {
                "attack_pct": 1.0,
                "defense_pct": 1.0,
                "lethality_pct": 0.5,
                "health_pct": 0.5,
            }
            for t in ("infantry", "cavalry", "archers")
        }
    )
    both_old_style_would_be_higher = score_enemy_march(march, catalog, troop_stats)
    # Zero report → hero+gear path
    hero_path = score_enemy_march(
        _complete_march(
            bonuses={
                t: {
                    "attack_pct": 0,
                    "defense_pct": 0,
                    "lethality_pct": 0,
                    "health_pct": 0,
                }
                for t in ("infantry", "cavalry", "archers")
            }
        ),
        catalog,
        troop_stats,
    )
    # With report set, score must equal report-only (not report+heroes).
    from ks.heroes.optimize.mystic_trial.enemy_proxy import (
        report_bonus_percent_maps,
        units_for_enemy_levels,
    )
    from ks.heroes.optimize.mystic_trial.proxy import score_march

    atk, defense, leth, hp = report_bonus_percent_maps(march["bonuses"])
    report_only = score_march(
        march["counts"],
        units_for_enemy_levels(march["levels"], troop_stats),
        atk_pct=atk,
        def_pct=defense,
        leth_pct=leth,
        hp_pct=hp,
    )
    assert both_old_style_would_be_higher.score == pytest.approx(report_only.score)
    assert both_old_style_would_be_higher.score != pytest.approx(hero_path.score)


def test_stronger_enemy_lowers_win_rate(catalog, troop_stats) -> None:
    stub = FloorStub(
        floor=10,
        enemy_ratio={"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3},
        enemy_power_scale=1.0,
        enemy_bonuses=empty_enemy_bonuses(),
    )
    player = MarchScore(
        score=1_000_000.0,
        offense_sum=1_000_000.0,
        tough_sum=1_000_000.0,
        by_type={
            "infantry": {"n": 1, "offense": 3e5, "tough": 3e5},
            "cavalry": {"n": 1, "offense": 3e5, "tough": 3e5},
            "archers": {"n": 1, "offense": 3e5, "tough": 3e5},
        },
    )
    weak = score_enemy_march(
        _complete_march(counts={"infantry": 1000, "cavalry": 1000, "archers": 1000}),
        catalog,
        troop_stats,
    )
    strong = score_enemy_march(
        _complete_march(
            counts={"infantry": 80000, "cavalry": 80000, "archers": 80000},
            gear_enhancement=80,
        ),
        catalog,
        troop_stats,
    )
    wr_weak = simulate_floor(player, stub, enemy=weak).win_rate
    wr_strong = simulate_floor(player, stub, enemy=strong).win_rate
    assert wr_strong < wr_weak
