"""Exclusive gear (widget level) scaling in optimiser scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.exclusive_gear import (
    widget_effect_at_level,
    widget_impacts_table,
    widget_level_from_hero,
)
from ks.heroes.models import ExclusiveGearRecord, HeroRecord
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.scoring import hero_strength
from ks.heroes.optimize.types import EffectTag

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "config" / "hero_catalog.yaml"


def test_widget_effect_at_level_linear_to_max() -> None:
    assert widget_effect_at_level(15.0, None) == 0.0
    assert widget_effect_at_level(15.0, 0) == 0.0
    assert widget_effect_at_level(15.0, 4) == pytest.approx(6.0)
    assert widget_effect_at_level(15.0, 10) == pytest.approx(15.0)


def test_widget_impacts_table_covers_levels_1_through_10() -> None:
    table = widget_impacts_table(15.0)
    assert len(table) == 10
    assert table[1] == pytest.approx(1.5)
    assert table[4] == pytest.approx(6.0)
    assert table[10] == pytest.approx(15.0)


def test_jabel_garrison_strength_scales_with_widget_level() -> None:
    catalog = load_catalog(None, CATALOG_PATH)
    entry = catalog["Jabel"]
    hero_base = HeroRecord(name="Jabel", stars=5, pellets=0, power=1_000_000)
    hero_l4 = HeroRecord(
        name="Jabel",
        stars=5,
        pellets=0,
        power=1_000_000,
        exclusive_gear=ExclusiveGearRecord(level=4, widget_name="Greaves of Faith"),
    )
    hero_l10 = HeroRecord(
        name="Jabel",
        stars=5,
        pellets=0,
        power=1_000_000,
        exclusive_gear=ExclusiveGearRecord(level=10, widget_name="Greaves of Faith"),
    )
    s0 = hero_strength(hero_base, entry, "garrison")
    s4 = hero_strength(hero_l4, entry, "garrison")
    s10 = hero_strength(hero_l10, entry, "garrison")
    assert s4 > s0
    assert s10 > s4
    assert widget_level_from_hero(hero_l4) == 4


def test_widget_tag_uses_level_not_stars() -> None:
    tag = EffectTag(kind="lethality_up", max_value=15.0, applies_to="widget")
    low_stars = HeroRecord(
        name="X",
        stars=0,
        exclusive_gear=ExclusiveGearRecord(level=10),
    )
    high_stars = HeroRecord(
        name="X",
        stars=5,
        exclusive_gear=ExclusiveGearRecord(level=10),
    )
    from ks.heroes.optimize.scoring import _effect_value

    assert _effect_value(tag, low_stars) == pytest.approx(15.0)
    assert _effect_value(tag, high_stars) == pytest.approx(15.0)
