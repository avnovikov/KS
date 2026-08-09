"""Skill level scaling for catalog-backed hero skills."""

from __future__ import annotations

from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.optimize.skill_effects import family_percents, leveled_catalog_percents
from ks.heroes.optimize.types import CatalogEntry, CatalogSkill, EffectTag


def _chenko_entry() -> CatalogEntry:
    return CatalogEntry(
        name="Chenko",
        troop="cavalry",
        effects=(
            EffectTag(kind="lethality_up", max_value=25.0, applies_to="expedition"),
            EffectTag(
                kind="damage_taken_down", max_value=20.0, applies_to="expedition"
            ),
        ),
        skills=(
            CatalogSkill(0, "Burst Fire", "conquest"),
            CatalogSkill(3, "Stand of Arms", "expedition", "lethality_up"),
            CatalogSkill(4, "Shield Wall", "expedition", "damage_taken_down"),
        ),
    )


def test_leveled_catalog_percents_scales_with_level() -> None:
    entry = _chenko_entry()
    low = HeroRecord(
        name="Chenko",
        skills=(
            SkillRecord(slot=3, name="Stand of Arms", level=1),
            SkillRecord(slot=4, name="Shield Wall", level=1),
        ),
    )
    high = HeroRecord(
        name="Chenko",
        skills=(
            SkillRecord(slot=3, name="Stand of Arms", level=5),
            SkillRecord(slot=4, name="Shield Wall", level=5),
        ),
    )
    assert leveled_catalog_percents(low, entry)["lethality_up"] == 5.0
    assert leveled_catalog_percents(high, entry)["lethality_up"] == 25.0
    assert leveled_catalog_percents(high, entry)["damage_taken_down"] == 20.0


def test_family_percents_prefers_levels_over_star_fallback() -> None:
    entry = _chenko_entry()
    hero = HeroRecord(
        name="Chenko",
        stars=5,
        pellets=0,
        skills=(SkillRecord(slot=3, name="Stand of Arms", level=5),),
    )
    merged, _incomplete = family_percents(hero, entry, family="expedition")
    assert merged["lethality_up"] == 25.0
