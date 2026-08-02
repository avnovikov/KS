"""Tests for scraped hero level XP / power ladder."""

from __future__ import annotations

from ks.heroes.optimize.hero_level_ladder import (
    load_hero_level_ladder,
    level_power_factor,
    xp_cost_between_hero_levels,
    xp_cost_next_hero_level,
)
from ks.heroes.ui.hero_power import scale_power_for_level_change


def test_ladder_loads_max_80() -> None:
    ladder = load_hero_level_ladder()
    assert ladder["max_level"] == 80
    assert 1 in ladder["by_level"]
    assert 80 in ladder["by_level"]
    assert ladder["by_level"][1]["xp_cost"] == 0
    assert ladder["by_level"][2]["xp_cost"] == 480


def test_xp_cost_next_and_between() -> None:
    ladder = load_hero_level_ladder()
    assert xp_cost_next_hero_level(ladder, 1) == 480
    assert xp_cost_next_hero_level(ladder, 80) is None
    assert xp_cost_between_hero_levels(ladder, 1, 3) == 480 + 690
    assert xp_cost_between_hero_levels(ladder, 5, 5) == 0


def test_power_factor_uses_deployment_capacity() -> None:
    ladder = load_hero_level_ladder()
    assert level_power_factor(ladder, 1) == 65.0
    assert level_power_factor(ladder, 10) == 970.0


def test_scale_power_for_level_change_ratio() -> None:
    ladder = load_hero_level_ladder()
    # L1 factor 65, L2 factor 140 → 1_000_000 * 140/65
    expected = round(1_000_000 * 140 / 65)
    assert (
        scale_power_for_level_change(1_000_000, 1, 2, ladder=ladder) == expected
    )


def test_scale_power_none_stays_none() -> None:
    assert scale_power_for_level_change(None, 1, 2) is None
