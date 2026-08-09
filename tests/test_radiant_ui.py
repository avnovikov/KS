"""Radiant Spire optimiser UI smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ks.heroes.models import HeroRecord, HeroStats  # noqa: E402
from ks.heroes.store import HeroStore  # noqa: E402
from ks.heroes.ui.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _seed_heroes(path: Path) -> None:
    store = HeroStore(path)
    roster = [
        ("Helga", "infantry"),
        ("Howard", "infantry"),
        ("Jabel", "cavalry"),
        ("Chenko", "cavalry"),
        ("Diana", "archers"),
        ("Quinn", "archers"),
    ]
    for i, (name, troop) in enumerate(roster):
        prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}[
            troop
        ]
        store.upsert(
            HeroRecord(
                name=name,
                power=2_000_000 - i * 10_000,
                troop_type=troop,
                rarity="legendary",
                stars=5,
                pellets=0,
                escorts=20_000,
                roster_page=0,
                roster_index=i,
                scraped_at="2026-08-09T00:00:00Z",
                stats=HeroStats(
                    expedition={
                        f"{prefix} Attack": 20.0,
                        f"{prefix} Defense": 10.0,
                        f"{prefix} Health": 10.0,
                        f"{prefix} Lethality": 15.0,
                    }
                ),
            )
        )


def _client(tmp_path: Path) -> TestClient:
    heroes = tmp_path / "heroes"
    heroes.mkdir()
    (heroes / "heroes.json").write_text("[]", encoding="utf-8")
    _seed_heroes(heroes)
    troops = tmp_path / "troops.yaml"
    troops.write_text(
        "\n".join(
            [
                "march_capacity: 100000",
                "truegold: 0",
                "infantry:",
                "  6: 200000",
                "cavalry:",
                "  6: 200000",
                "archers:",
                "  6: 200000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return TestClient(
        create_app(
            gear_dir=None,
            heroes_dir=heroes,
            troops_path=troops,
            governor_dir=tmp_path / "governor",
        )
    )


def test_radiant_page_and_api(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get("/optimiser/radiant-spire")
    assert page.status_code == 200
    assert "Radiant Spire" in page.text
    assert "optimiser_radiant_spire.js" in page.text

    api = client.get("/api/optimize/radiant-spire")
    assert api.status_code == 200, api.text
    body = api.json()
    assert "Proxy score" in body["proxy_banner"]
    assert body["active_marches"] == 2
    assert len([m for m in body["marches"] if m]) == 2
    used = [h for m in body["marches"] if m for h in m["hero_names"]]
    assert len(used) == len(set(used))
    assert body["lineup_score"] > 0
