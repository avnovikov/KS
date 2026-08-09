"""API tests for overwriting hero skill levels."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ks.heroes.models import HeroRecord  # noqa: E402
from ks.heroes.store import HeroStore  # noqa: E402
from ks.heroes.ui.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _client(tmp_path: Path) -> TestClient:
    heroes = tmp_path / "heroes"
    heroes.mkdir()
    (heroes / "heroes.json").write_text('{"heroes":[]}', encoding="utf-8")
    store = HeroStore(heroes)
    store.upsert(
        HeroRecord(
            name="Chenko",
            power=100,
            troop_type="cavalry",
            rarity="epic",
            stars=3,
            pellets=0,
            roster_page=0,
            roster_index=0,
            scraped_at="2026-08-09T00:00:00Z",
        )
    )
    return TestClient(create_app(gear_dir=None, heroes_dir=heroes))


def test_get_hero_includes_catalog_skills(tmp_path: Path) -> None:
    client = _client(tmp_path)
    res = client.get("/api/heroes/Chenko")
    assert res.status_code == 200
    body = res.json()
    assert body["hero"]["name"] == "Chenko"
    assert any(s["name"] == "Stand of Arms" for s in body["catalog_skills"])


def test_patch_skills_overwrites_levels(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = {
        "skills": [
            {"slot": 0, "name": "Burst Fire", "level": 2},
            {"slot": 3, "name": "Stand of Arms", "level": 5},
            {"slot": 4, "name": "Shield Wall", "level": 4},
        ]
    }
    res = client.patch("/api/heroes/Chenko/skills", json=payload)
    assert res.status_code == 200, res.text
    levels = {s["slot"]: s["level"] for s in res.json()["hero"]["skills"]}
    assert levels[3] == 5
    assert levels[4] == 4

    again = client.get("/api/heroes/Chenko")
    levels2 = {s["slot"]: s["level"] for s in again.json()["hero"]["skills"]}
    assert levels2[3] == 5
