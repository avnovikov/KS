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
    page = client.get("/optimiser/events/mystic-trial/radiant-spire")
    assert page.status_code == 200
    assert "Radiant Spire" in page.text
    assert "Mystic Trial" in page.text
    assert "optimiser_radiant_spire.js" in page.text
    assert "optimiser_board.js" in page.text
    assert 'aria-label="Mystic Trial room"' in page.text
    assert 'id="gear-detail-modal"' in page.text

    legacy = client.get("/optimiser/radiant-spire", follow_redirects=False)
    assert legacy.status_code == 302
    assert legacy.headers["location"] == "/optimiser/events/mystic-trial/radiant-spire"

    api = client.get("/api/optimize/radiant-spire")
    assert api.status_code == 200, api.text
    body = api.json()
    assert "Proxy score" in body["proxy_banner"]
    assert body["active_marches"] == 2
    assert len([m for m in body["marches"] if m]) == 2
    used = [h for m in body["marches"] if m for h in m["hero_names"]]
    assert len(used) == len(set(used))
    assert body["lineup_score"] > 0


def test_radiant_api_includes_gear_assignment_with_icons(tmp_path: Path) -> None:
    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore

    heroes = tmp_path / "heroes"
    heroes.mkdir()
    (heroes / "heroes.json").write_text("[]", encoding="utf-8")
    _seed_heroes(heroes)
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    store = GearStore(gear_dir)
    for i, (slot, troop) in enumerate(
        [
            ("helmet", "infantry"),
            ("chest", "infantry"),
            ("gloves", "infantry"),
            ("boots", "infantry"),
            ("helmet", "cavalry"),
            ("chest", "cavalry"),
            ("gloves", "cavalry"),
            ("boots", "cavalry"),
            ("helmet", "archers"),
            ("chest", "archers"),
            ("gloves", "archers"),
            ("boots", "archers"),
        ]
    ):
        store.upsert(
            GearRecord(
                piece_id=f"p{i}",
                name=f"{troop} {slot}",
                troop_type=troop,
                slot=slot,
                rarity="mythic",
                enhancement_level=10,
                power=50_000,
            )
        )
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
    client = TestClient(
        create_app(
            gear_dir=gear_dir,
            heroes_dir=heroes,
            troops_path=troops,
            governor_dir=tmp_path / "governor",
        )
    )
    body = client.get("/api/optimize/radiant-spire").json()
    march = next(m for m in body["marches"] if m)
    assert march.get("gear_assignment")
    first_hero = next(iter(march["gear_assignment"].values()))
    assert any(p.get("icon_url") for p in first_hero)
    assert any(p.get("slot") for p in first_hero)
