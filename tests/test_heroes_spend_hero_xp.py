"""Tests for Hero EXP allocation (greedy ΔU over levels)."""

from __future__ import annotations

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.hero_level_ladder import load_hero_level_ladder
from ks.heroes.optimize.spend_hero_xp import allocate_hero_exp, apply_hero_levels


def _hero(
    name: str,
    *,
    level: int = 1,
    power: int = 1_000_000,
) -> HeroRecord:
    return HeroRecord(
        name=name,
        level=level,
        power=power,
        stars=1,
        pellets=0,
        scraped_at="t",
    )


def test_allocate_prefers_hero_that_raises_utility() -> None:
    heroes = [_hero("A", level=1), _hero("B", level=1)]

    def utility(hs: list[HeroRecord]):
        levels = {h.name: int(h.level or 0) for h in hs}
        u = 100.0 * levels.get("A", 0) + 1.0 * levels.get("B", 0)
        return u, {"levels": levels}

    # 480 XP = one level from 1→2
    result = allocate_hero_exp(heroes, 480, utility, event="test", max_steps=3)
    assert result.best_utility > result.baseline_utility
    assert result.steps
    assert result.steps[0].name == "A"
    assert result.steps[0].from_level == 1
    assert result.steps[0].to_level == 2
    assert result.leftover_exp == 0


def test_allocate_respects_max_level() -> None:
    ladder = load_hero_level_ladder()
    heroes = [_hero("A", level=80)]

    def utility(hs: list[HeroRecord]):
        return float(hs[0].level or 0), {}

    result = allocate_hero_exp(
        heroes, 10_000_000, utility, event="test", max_steps=5, ladder=ladder
    )
    assert result.steps == ()
    assert result.leftover_exp == 10_000_000


def test_allocate_stops_when_no_positive_delta() -> None:
    heroes = [_hero("A", level=1)]

    def utility(hs: list[HeroRecord]):
        return 1.0, {}

    result = allocate_hero_exp(heroes, 10_000, utility, event="test", max_steps=5)
    assert result.steps == ()
    assert result.leftover_exp == 10_000


def test_apply_hero_levels_rescales_power() -> None:
    ladder = load_hero_level_ladder()
    heroes = [_hero("A", level=1, power=65_000)]
    out = apply_hero_levels(heroes, {"A": 2}, ladder=ladder)
    # f(1)=65, f(2)=140 → 65000 * 140/65 = 140000
    assert out[0].level == 2
    assert out[0].power == 140_000
