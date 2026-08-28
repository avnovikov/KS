import pytest

from ks.heroes.models import ExclusiveGearRecord, HeroRecord
from ks.heroes.optimize.scoring import hero_strength, max_power_by_troop
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def _entry(name: str, widget: str, *effects: EffectTag) -> CatalogEntry:
    return CatalogEntry(name=name, widget_type=widget, effects=effects)


def _hero(stars: int = 5) -> HeroRecord:
    return HeroRecord(
        name="x",
        stars=stars,
        exclusive_gear=ExclusiveGearRecord(level=10),
    )


def test_garrison_prefers_defense_widget() -> None:
    zoe = _entry(
        "Zoe",
        "defense",
        EffectTag("defender_attack", 15.0, "widget"),
        EffectTag("attack_up", 25.0, "expedition"),
    )
    amadeus = _entry(
        "Amadeus",
        "attack",
        EffectTag("rally_attack", 15.0, "widget"),
        EffectTag("attack_up", 25.0, "expedition"),
    )
    hero = _hero()
    assert hero_strength(hero, zoe, "garrison") > hero_strength(hero, amadeus, "garrison")


def test_rally_prefers_attack_widget() -> None:
    zoe = _entry(
        "Zoe",
        "defense",
        EffectTag("defender_attack", 15.0, "widget"),
        EffectTag("attack_up", 25.0, "expedition"),
    )
    amadeus = _entry(
        "Amadeus",
        "attack",
        EffectTag("rally_attack", 15.0, "widget"),
        EffectTag("attack_up", 25.0, "expedition"),
    )
    hero = _hero()
    assert hero_strength(hero, amadeus, "rally_lead") > hero_strength(hero, zoe, "rally_lead")


def test_solo_ignores_widget_tags() -> None:
    with_widget = _entry(
        "Amadeus",
        "attack",
        EffectTag("rally_attack", 100.0, "widget"),
        EffectTag("attack_up", 10.0, "expedition"),
    )
    no_widget = _entry(
        "Other",
        "none",
        EffectTag("attack_up", 10.0, "expedition"),
    )
    hero = HeroRecord(name="x", stars=1)
    assert hero_strength(hero, with_widget, "solo") == hero_strength(hero, no_widget, "solo")


def test_max_power_by_troop_uses_best_geared_hero_per_class() -> None:
    heroes = [
        HeroRecord(name="Gordon", power=200_000),
        HeroRecord(name="Jabel", power=500_000),
        HeroRecord(name="Howard", power=300_000),
    ]
    catalog = {
        "Gordon": CatalogEntry(name="Gordon", troop="cavalry"),
        "Jabel": CatalogEntry(name="Jabel", troop="cavalry"),
        "Howard": CatalogEntry(name="Howard", troop="infantry"),
    }
    assert max_power_by_troop(heroes, catalog) == {
        "cavalry": 500_000,
        "infantry": 300_000,
    }


def test_hero_strength_uses_fungible_class_power() -> None:
    """Gear is fungible within troop class; power term uses class max."""
    entry = CatalogEntry(name="Gordon", troop="cavalry", widget_type="none")
    weak = HeroRecord(name="Gordon", power=200_000, stars=1)
    with_own = hero_strength(weak, entry, "solo")
    with_best = hero_strength(weak, entry, "solo", effective_power=500_000)
    assert with_best - with_own == pytest.approx(0.3)
