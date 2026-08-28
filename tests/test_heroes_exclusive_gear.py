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
from ks.heroes.optimize.types import CatalogEntry, EffectTag, Scenario
from ks.heroes.optimize.explain import fits_because_event

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


def test_widget_priority_bonus_scales_linearly_with_level() -> None:
    entry = CatalogEntry(
        name="J",
        widget_type="defense",
        garrison_widget_priority=4,
        effects=(),
    )
    h0 = HeroRecord(name="J", exclusive_gear=ExclusiveGearRecord(level=0))
    h4 = HeroRecord(name="J", exclusive_gear=ExclusiveGearRecord(level=4))
    h10 = HeroRecord(name="J", exclusive_gear=ExclusiveGearRecord(level=10))
    assert hero_strength(h0, entry, "garrison") == pytest.approx(0.0)
    assert hero_strength(h4, entry, "garrison") == pytest.approx(8.0)
    assert hero_strength(h10, entry, "garrison") == pytest.approx(20.0)

    rally = CatalogEntry(
        name="R",
        widget_type="attack",
        rally_widget_priority=3,
        effects=(),
    )
    assert hero_strength(h4, rally, "rally_lead") == pytest.approx(6.0)
    assert hero_strength(h10, rally, "rally_lead") == pytest.approx(15.0)


def test_fits_because_event_shows_widget_level_and_effective_percent() -> None:
    catalog = load_catalog(None, CATALOG_PATH)
    scenario = Scenario(mode="garrison", combat_rate=1.0)
    hero_l4 = HeroRecord(
        name="Jabel",
        exclusive_gear=ExclusiveGearRecord(level=4, max_level=10),
    )
    bits = fits_because_event(
        "Jabel", catalog, "garrison", scenario, hero=hero_l4
    )
    joined = " ".join(bits)
    assert "Exclusive gear L4/10" in joined
    assert "lethality_up effective=6.0%" in joined

    hero_unset = HeroRecord(name="Jabel")
    unset_bits = fits_because_event(
        "Jabel", catalog, "garrison", scenario, hero=hero_unset
    )
    assert any("level unset" in bit for bit in unset_bits)


def test_exclusive_gear_record_roundtrip() -> None:
    record = ExclusiveGearRecord(
        level=4,
        max_level=10,
        widget_name="Greaves of Faith",
        widget_type="defense",
        source="manual",
        updated_at="2026-08-28T10:00:00+00:00",
    )
    assert ExclusiveGearRecord.from_dict(record.to_dict()) == record

