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
