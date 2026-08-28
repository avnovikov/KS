"""Widget skill synthesis and optimiser coverage."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.models import ExclusiveGearRecord, HeroRecord
from ks.heroes.optimize.bear_damage import host_skillmod_buckets
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.scoring import hero_strength
from ks.heroes.optimize.skill_effects import widget_skill_percents
from ks.heroes.optimize.types import CatalogEntry, EffectTag

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_synthesizes_widget_skill_for_marlin() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    marlin = catalog["Marlin"]
    widget = [s for s in marlin.skills if s.family == "widget"]
    assert len(widget) == 1
    assert widget[0].name == "Mistweaver"
    assert widget[0].effect_kind == "rally_lethality"


def test_catalog_keeps_explicit_helga_widget_skill() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    helga = catalog["Helga"]
    widget = [s for s in helga.skills if s.family == "widget"]
    assert len(widget) == 1
    assert widget[0].name == "Zeal"


def test_widget_skill_percents_scale_with_exclusive_gear_level() -> None:
    entry = CatalogEntry(
        name="Marlin",
        widget_type="attack",
        widget_name="Mistweaver",
        effects=(EffectTag("rally_lethality", 15.0, "widget"),),
        skills=(
            __import__("ks.heroes.optimize.types", fromlist=["CatalogSkill"]).CatalogSkill(
                slot=7,
                name="Mistweaver",
                family="widget",
                effect_kind="rally_lethality",
            ),
        ),
    )
    bare = HeroRecord(name="Marlin", stars=3)
    leveled = HeroRecord(
        name="Marlin",
        stars=3,
        exclusive_gear=ExclusiveGearRecord(level=5, max_level=10),
    )
    assert widget_skill_percents(bare, entry) == {}
    assert widget_skill_percents(leveled, entry)["rally_lethality"] == 7.5


def test_hero_strength_uses_widget_skill_when_present() -> None:
    entry = CatalogEntry(
        name="Marlin",
        widget_type="attack",
        rally_widget_priority=3,
        effects=(
            EffectTag("rally_lethality", 15.0, "widget"),
            EffectTag("lethality_up", 25.0, "expedition"),
        ),
        skills=(
            __import__("ks.heroes.optimize.types", fromlist=["CatalogSkill"]).CatalogSkill(
                slot=7,
                name="Mistweaver",
                family="widget",
                effect_kind="rally_lethality",
            ),
        ),
    )
    hero = HeroRecord(
        name="Marlin",
        stars=3,
        exclusive_gear=ExclusiveGearRecord(level=10, max_level=10),
    )
    score = hero_strength(hero, entry, "rally_lead")
    assert score > hero_strength(
        HeroRecord(name="Marlin", stars=3, exclusive_gear=ExclusiveGearRecord(level=0)),
        entry,
        "rally_lead",
    )


def test_bear_host_skillmod_scales_widget_by_exclusive_gear_level() -> None:
    entry = CatalogEntry(
        name="Amadeus",
        effects=(
            EffectTag("rally_attack", 15.0, "widget", effect_op=102),
            EffectTag("attack_up", 25.0, "expedition", effect_op=102),
        ),
    )
    bare = HeroRecord(name="Amadeus", stars=5)
    leveled = HeroRecord(
        name="Amadeus",
        stars=5,
        exclusive_gear=ExclusiveGearRecord(level=10, max_level=10),
    )
    empty = host_skillmod_buckets([(bare, entry)])
    full = host_skillmod_buckets([(leveled, entry)])
    assert empty["damage_up"].get(102, 0.0) < full["damage_up"].get(102, 0.0)
