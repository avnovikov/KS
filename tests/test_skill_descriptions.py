"""Tests for kingshotdata skill description enrichment."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.skill_descriptions import enrich_catalog_skills, load_skill_descriptions_by_hero

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTIONS = ROOT / "config" / "hero_skill_descriptions.json"


def test_load_skill_descriptions_has_marlin_tidal_rush() -> None:
    by_hero = load_skill_descriptions_by_hero(str(DESCRIPTIONS))
    marlin = by_hero["Marlin"]["Tidal Rush"]
    assert marlin["description"]
    assert "tidal" in marlin["description"].lower()
    assert marlin["upgrade_preview"]


def test_enrich_catalog_skills_attaches_text() -> None:
    base = [
        {"slot": 0, "name": "Tidal Rush", "family": "conquest", "effect_kind": "damage_up"},
    ]
    enriched = enrich_catalog_skills(
        "Marlin",
        base,
        descriptions_path=str(DESCRIPTIONS),
    )
    assert enriched[0]["description"]
    assert enriched[0]["upgrade_preview"]
    assert enriched[0]["slot"] == 0


def test_enrich_leaves_unknown_skills_unchanged() -> None:
    base = [{"slot": 0, "name": "Not A Real Skill", "family": "conquest"}]
    enriched = enrich_catalog_skills(
        "Marlin",
        base,
        descriptions_path=str(DESCRIPTIONS),
    )
    assert "description" not in enriched[0]
