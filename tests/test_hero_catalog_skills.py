"""Tests for catalog skill definitions on CatalogEntry."""

from __future__ import annotations

from pathlib import Path

import yaml

from ks.heroes.optimize.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_load_catalog_skills_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yaml"
    path.write_text(
        yaml.dump(
            {
                "heroes": {
                    "Chenko": {
                        "troop": "cavalry",
                        "rarity": "epic",
                        "effects": [
                            {
                                "kind": "lethality_up",
                                "max_value": 25.0,
                                "applies_to": "expedition",
                            }
                        ],
                        "skills": [
                            {
                                "slot": 0,
                                "name": "Burst Fire",
                                "family": "conquest",
                            },
                            {
                                "slot": 3,
                                "name": "Stand of Arms",
                                "family": "expedition",
                                "effect_kind": "lethality_up",
                            },
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    catalog = load_catalog(None, path)
    skills = catalog["Chenko"].skills
    assert len(skills) == 2
    assert skills[0].slot == 0
    assert skills[0].name == "Burst Fire"
    assert skills[0].family == "conquest"
    assert skills[0].effect_kind is None
    assert skills[1].effect_kind == "lethality_up"


def test_repo_catalog_loads_after_seed() -> None:
    """Smoke: catalog file remains loadable (skills optional until seeded)."""
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    assert "Chenko" in catalog


def test_diana_combat_skills_have_effect_kinds() -> None:
    """Diana's conquest combat skills must map so leveled_catalog_percents works."""
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    by_slot = {s.slot: s for s in catalog["Diana"].skills}
    assert by_slot[0].effect_kind == "aoe_damage_up"
    assert by_slot[1].effect_kind == "attack_speed_up"
    assert by_slot[2].effect_kind == "crit_rate_up"
    assert by_slot[3].effect_kind is None  # stamina economy
    assert by_slot[4].effect_kind is None  # wilderness march


def test_saul_superior_techniques_is_attack_speed() -> None:
    catalog = load_catalog(None, ROOT / "config" / "hero_catalog.yaml")
    skill = next(s for s in catalog["Saul"].skills if s.name == "Superior Techniques")
    assert skill.effect_kind == "attack_speed_up"
