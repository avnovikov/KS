import pytest

from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.optimize.skill_effects import (
    CONQUEST,
    EXPEDITION,
    catalog_percents,
    family_percents,
    kind_family,
    skill_kind,
    skill_percents,
)
from ks.heroes.optimize.types import CatalogEntry, EffectTag


def _skill(slot: int, preview: str | None, bonus: float | None) -> SkillRecord:
    return SkillRecord(slot=slot, upgrade_preview=preview, current_bonus=bonus)


def test_skill_kind_maps_known_labels() -> None:
    assert skill_kind("Attack Up: 8%/12%/15%/20%/24%") == "attack_up"
    assert skill_kind("Damage Taken Chance Down: 8%/16%") == "damage_taken_down"
    assert skill_kind("Area of Effect Damage Up: 180%/198%") == "aoe_damage_up"
    assert skill_kind("Lethality Up:5%/10%/15%") == "lethality_up"


def test_skill_kind_ignores_economy_labels() -> None:
    assert skill_kind("Mill Income: 5%/10%/15%") is None
    assert skill_kind("Bread Gathering Speed: 5%/10%") is None
    assert skill_kind(None) is None
    assert skill_kind("") is None


def test_skill_percents_sums_per_kind_and_flags_missing() -> None:
    hero = HeroRecord(
        name="Forrest",
        skills=(
            _skill(2, "Attack Up: 8%/12%/15%/20%/24%", 16.0),
            _skill(3, "Lethality Up:5%/10%/15%/20%/25%", 15.0),
            _skill(1, "Defense Up: 25%/37.5%/50%", 50.0),
            _skill(5, "Damage Taken Down: 4%/8%/12%", 6.0),
        ),
    )
    percents, incomplete = skill_percents(hero)
    assert percents == {
        "attack_up": 16.0,
        "lethality_up": 15.0,
        "defense_up": 50.0,
        "damage_taken_down": 6.0,
    }
    assert incomplete is False


def test_skill_percents_flags_incomplete_when_bonus_missing() -> None:
    hero = HeroRecord(
        name="Quinn",
        skills=(
            _skill(0, "Damage Up: 400%/440%", None),
            _skill(2, "Attack Up: 8%/12%", 12.0),
        ),
    )
    percents, incomplete = skill_percents(hero)
    assert percents == {"attack_up": 12.0}
    assert incomplete is True


def test_skill_percents_flags_incomplete_when_no_skills() -> None:
    percents, incomplete = skill_percents(HeroRecord(name="Nobody"))
    assert percents == {}
    assert incomplete is True


def test_catalog_percents_scales_max_value_by_stars() -> None:
    entry = CatalogEntry(
        name="Amadeus",
        effects=(
            EffectTag("attack_up", 25.0, "expedition"),
            EffectTag("rally_attack", 15.0, "widget"),
        ),
    )
    full = catalog_percents(entry, 5, 0)
    assert full["attack_up"] == pytest.approx(25.0)
    assert "rally_attack" not in full
    half = catalog_percents(entry, 0, 0)
    assert half["attack_up"] < full["attack_up"]


def test_kind_family_uses_catalog_applies_to() -> None:
    catalog = {
        "A": CatalogEntry(name="A", effects=(EffectTag("attack_up", 25.0, "conquest"),)),
    }
    assert kind_family("attack_up", catalog) == CONQUEST
    assert kind_family("attack_up", None) == EXPEDITION


def test_kind_family_excludes_widget_only_kinds() -> None:
    catalog = {
        "A": CatalogEntry(name="A", effects=(EffectTag("rally_attack", 15.0, "widget"),)),
    }
    assert kind_family("rally_attack", catalog) is None


def test_family_percents_filters_to_requested_family() -> None:
    hero = HeroRecord(
        name="Forrest",
        stars=3,
        pellets=0,
        skills=(
            _skill(2, "Attack Up: 8%/12%", 16.0),
            _skill(0, "Area of Effect Damage Up: 55%/60%", 65.0),
        ),
    )
    entry = CatalogEntry(name="Forrest", effects=())
    exp, _ = family_percents(hero, entry, family=EXPEDITION)
    con, _ = family_percents(hero, entry, family=CONQUEST)
    assert exp == {"attack_up": 16.0}
    assert con == {"aoe_damage_up": 65.0}


def test_family_percents_falls_back_to_catalog_when_scrape_empty() -> None:
    hero = HeroRecord(name="Amadeus", stars=5, pellets=0, skills=())
    entry = CatalogEntry(
        name="Amadeus",
        effects=(EffectTag("attack_up", 25.0, "expedition"),),
    )
    percents, incomplete = family_percents(hero, entry, family=EXPEDITION)
    assert percents["attack_up"] == pytest.approx(25.0)
    assert incomplete is True


def test_kind_family_returns_none_for_widget_only_defender_kinds() -> None:
    for kind in ("defender_attack", "defender_defense", "defender_health"):
        assert kind_family(kind) is None
        assert kind_family(kind, {}) is None
