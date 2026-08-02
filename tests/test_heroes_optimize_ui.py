"""Optimize UI page + API (sword/bear/arena/conquest)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore


ROOT = Path(__file__).resolve().parents[1]


def _seed_roster(tmp_path: Path) -> Path:
    store = HeroStore(tmp_path)
    rows = [
        ("Amadeus", "infantry", "legendary", 5, 900_000),
        ("Hilde", "infantry", "legendary", 4, 700_000),
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
        ("Marlin", "archer", "legendary", 3, 350_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
    ]
    for i, (name, troop, rarity, stars, power) in enumerate(rows):
        store.upsert(
            HeroRecord(
                name=name,
                troop_type=troop,
                rarity=rarity,
                stars=stars,
                pellets=0,
                power=power,
                escorts=5,
                roster_page=0,
                roster_index=i,
                scraped_at="t",
            )
        )
    return tmp_path


def test_optimize_page_and_api(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
    client = TestClient(create_app(heroes_dir=heroes_dir))

    hub = client.get("/optimize")
    assert hub.status_code == 200
    assert b"Optimize" in hub.content
    assert b'href="/optimize/events"' in hub.content
    assert b'href="/optimize/gear-xp"' in hub.content

    page = client.get("/optimize/events")
    assert page.status_code == 200
    assert b"Swordland" in page.content
    assert b"Bear" in page.content
    assert b"Arena" in page.content
    assert b"Conquest" in page.content
    assert b"conquest-block" in page.content
    assert b'href="/heroes"' in page.content
    assert b"Regenerate" in page.content
    assert b"gear-detail-modal" in page.content
    assert b"data-regen=" in page.content

    gear_xp = client.get("/optimize/gear-xp")
    assert gear_xp.status_code == 200
    assert b"Gear XP spend" in gear_xp.content
    assert b"grey" in gear_xp.content

    heroes_page = client.get("/heroes")
    assert b'href="/optimize"' in heroes_page.content

    payload = client.get("/api/optimize").json()
    assert "sword" in payload
    assert "bear" in payload
    assert "arena" in payload
    assert "conquest" in payload
    sword_modes = payload["sword"]["modes"]
    assert set(sword_modes) >= {"garrison", "rally_lead", "joiner", "solo"}
    for mode, row in sword_modes.items():
        assert row["recommended_mode"] == mode
        assert row["expected_personal_points"] > 0
        assert len(row["heroes"]) == 3
        assert row["heroes"][0].get("explain", {}).get("leave_one_out")
    bear_modes = payload["bear"]["modes"]
    assert len(bear_modes) >= 2
    for mode, row in bear_modes.items():
        assert row["recommended_mode"] == mode
        assert row["expected_personal_points"] > 0
    arena = payload["arena"]
    assert arena["attack"]["side"] == "attack"
    assert arena["attack"]["status"] == "Optimal"
    assert set(arena["attack"]["formation"]) == {"F1", "F2", "B1", "B2", "B3"}
    assert arena["defense"]["side"] == "defense"
    assert arena["defense"]["status"] == "Optimal"
    conquest = payload["conquest"]
    assert conquest["mode"] == "conquest"
    assert conquest["status"] == "Optimal"
    assert set(conquest["formation"]) == {"F1", "F2", "B1", "B2", "B3"}
    assert len(conquest["heroes"]) == 5


def test_optimize_gear_xp_api_smoke(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore
    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    store = GearStore(gear_dir)
    store.upsert(
        GearRecord(
            piece_id="helm1",
            name="Inf helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=5,
            power=40_000,
        )
    )
    client = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))
    # No gear → 400 when heroes-only app
    heroes_only = TestClient(create_app(heroes_dir=heroes_dir))
    denied = heroes_only.post(
        "/api/optimize/gear-xp",
        json={"event": "arena_attack", "grey": 1},
    )
    assert denied.status_code == 400

    res = client.post(
        "/api/optimize/gear-xp",
        json={
            "event": "arena_attack",
            "grey": 2,
            "green": 0,
            "blue": 0,
            "purple": 0,
            "part_100": 0,
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert "baseline_utility" in payload
    assert "best_utility" in payload
    assert "steps" in payload
    assert "leftover" in payload
    assert payload["event"] == "arena_attack"


def test_optimize_api_includes_gear_assignment_with_icons(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore
    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
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
    client = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))
    payload = client.get("/api/optimize").json()
    garrison = payload["sword"]["modes"]["garrison"]
    assert garrison.get("gear_assignment")
    first_hero = next(iter(garrison["gear_assignment"].values()))
    assert any(p.get("icon_url") for p in first_hero)
    attack = payload["arena"]["attack"]
    assert attack.get("gear_assignment")


def test_optimize_requires_heroes(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore
    from ks.heroes.ui.app import create_app

    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="cell0",
            name="Helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=1,
            power=1000,
        )
    )
    client = TestClient(create_app(gear_dir))
    assert client.get("/optimize").status_code == 404
    assert client.get("/api/optimize").status_code == 404
