import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import hero_strength, max_power_by_troop
from ks.heroes.optimize.stat_contributions import EXPEDITION, Share, StatContribution
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def _entry(name: str, widget: str, *effects: EffectTag) -> CatalogEntry:
    return CatalogEntry(name=name, widget_type=widget, effects=effects)


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
    hero = HeroRecord(name="x", stars=5)
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
    hero = HeroRecord(name="x", stars=5)
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


def _contribution(power: float, lethality: float = 0.0) -> StatContribution:
    return StatContribution(
        family=EXPEDITION,
        estimated=True,
        skills_incomplete=False,
        power=Share(hero=power, skills=0.0, gear=0.0),
        stats={"Infantry Lethality": Share(0.0, 0.0, lethality)},
    )


def test_hero_strength_uses_fungible_class_power() -> None:
    """Gear is fungible within troop class; power term uses class max.

    ``effective_power`` is gone — callers now feed the class-max power into
    ``hero_contribution`` (see model.py's ``_compute_hero_features``) and
    pass the resulting contribution here.
    """
    entry = CatalogEntry(name="Gordon", troop="cavalry", widget_type="none")
    weak = HeroRecord(name="Gordon", power=200_000, stars=1)
    with_own = hero_strength(weak, entry, "solo", contribution=_contribution(200_000))
    with_best = hero_strength(weak, entry, "solo", contribution=_contribution(500_000))
    assert with_best > with_own


def test_hero_strength_rises_with_contribution_power() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    low = hero_strength(hero, entry, "solo", contribution=_contribution(100_000))
    high = hero_strength(hero, entry, "solo", contribution=_contribution(900_000))
    assert high > low


def test_hero_strength_rises_with_contribution_gear_percent() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    bare = hero_strength(hero, entry, "solo", contribution=_contribution(100_000))
    geared = hero_strength(
        hero, entry, "solo", contribution=_contribution(100_000, lethality=40.0)
    )
    assert geared > bare


def test_hero_strength_without_contribution_scores_effects_only() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    assert hero_strength(hero, entry, "solo") == hero_strength(
        hero, entry, "solo", contribution=None
    )


def test_hero_strength_rejects_conquest_contribution() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3)
    wrong = StatContribution(
        family="conquest",
        estimated=True,
        skills_incomplete=False,
        power=Share(1.0, 0.0, 0.0),
        stats={},
    )
    with pytest.raises(ValueError, match="expedition"):
        hero_strength(hero, entry, "solo", contribution=wrong)
