"""API tests for Radiant stage·round opponent persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ks.heroes.models import HeroRecord, HeroStats  # noqa: E402
from ks.heroes.store import HeroStore  # noqa: E402
from ks.heroes.ui.app import create_app  # noqa: E402


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
    governor = tmp_path / "governor"
    governor.mkdir()
    return TestClient(
        create_app(
            gear_dir=None,
            heroes_dir=heroes,
            troops_path=troops,
            governor_dir=governor,
        )
    )


def test_put_and_reload_opponent_slot(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = {
        "hero_names": ["Helga", "Jabel", "Diana"],
        "hero_level": 80,
        "gear_enhancement": 40,
        "levels": {"infantry": 7, "cavalry": 6, "archers": 6},
        "counts": {"infantry": 42000, "cavalry": 18000, "archers": 15000},
        "bonuses": {
            "infantry": {
                "attack_pct": 120,
                "defense_pct": 80,
                "lethality_pct": 0,
                "health_pct": 0,
            }
        },
    }
    put = client.put("/api/mystic-trial/radiant-opponents/3/2/0", json=body)
    assert put.status_code == 200, put.text
    path = Path(put.json()["path"])
    assert path.is_file()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["stages"]["3"]["2"]["marches"][0]["counts"]["infantry"] == 42000
    assert raw["stages"]["3"]["2"]["marches"][0]["hero_names"] == [
        "Helga",
        "Jabel",
        "Diana",
    ]

    opt = client.get("/api/optimize/radiant-spire?stage=3&round=2")
    assert opt.status_code == 200, opt.text
    payload = opt.json()
    assert payload.get("opponent")
    assert payload["opponent"].get("saved") is True
    assert "Helga" in (payload.get("catalog_hero_names") or [])
    march0 = payload["opponent"]["marches"][0]
    assert march0["hero_names"] == ["Helga", "Jabel", "Diana"]
    assert march0["hero_level"] == 80
    assert march0["gear_enhancement"] == 40
    assert march0["levels"]["infantry"] == 7
    assert march0["counts"]["infantry"] == 42000
    assert march0["bonuses"]["infantry"]["attack_pct"] == 120.0
    assert payload.get("floor", {}).get("enemy_proxy") is True
    mc = (payload["marches"][0] or {}).get("breakdown", {}).get("mc") or {}
    assert mc.get("enemy_score", 0) > 0


def test_proxy_only_without_round_hides_opponent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.put(
        "/api/mystic-trial/radiant-opponents/3/2/0",
        json={
            "levels": {"infantry": 6, "cavalry": 6, "archers": 6},
            "counts": {"infantry": 10, "cavalry": 0, "archers": 0},
            "bonuses": {},
        },
    )
    # stage alone (legacy floor) without round → no opponent panel
    res = client.get("/api/optimize/radiant-spire?stage=3")
    assert res.status_code == 200
    assert res.json().get("opponent") is None

    # floor alias alone also proxy-only now (round required)
    legacy = client.get("/api/optimize/radiant-spire?floor=3")
    assert legacy.status_code == 200
    assert legacy.json().get("opponent") is None
