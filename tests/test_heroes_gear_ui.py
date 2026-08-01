"""Tests for gear UI level updates (no live server required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_store import GearStore
from ks.heroes.ui.app import update_piece_levels


def _seed(tmp_path: Path) -> GearStore:
    store = GearStore(tmp_path)
    store.upsert(
        GearRecord(
            piece_id="cell0",
            name="Judicator's Armet",
            troop_type="cavalry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=51,
            mastery_level=2,
            power=152100,
        )
    )
    return store


def test_update_enhancement_persists_json_and_db(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    updated = update_piece_levels(store, "cell0", enhancement_level=55)
    assert updated.enhancement_level == 55
    assert updated.mastery_level == 2
    # Mythic +55 M2 power from fitted curve (higher than +51 M2 = 152100)
    assert updated.power is not None and updated.power > 152100

    raw = json.loads((tmp_path / "gear.json").read_text(encoding="utf-8"))
    assert raw["gear"][0]["enhancement_level"] == 55
    assert raw["gear"][0]["power"] == updated.power

    reloaded = GearStore(tmp_path)
    piece = next(p for p in reloaded.all_pieces() if p.piece_id == "cell0")
    assert piece.enhancement_level == 55
    assert piece.power == updated.power


def test_clear_mastery(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    updated = update_piece_levels(store, "cell0", mastery_level=None)
    assert updated.mastery_level is None


def test_rejects_out_of_range_enhancement(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    with pytest.raises(ValueError, match="0..200"):
        update_piece_levels(store, "cell0", enhancement_level=201)


def test_unknown_piece(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    with pytest.raises(KeyError):
        update_piece_levels(store, "missing", enhancement_level=1)


def test_fastapi_patch_roundtrip(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app
    from ks.heroes.ui.power import compute_gear_power

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.patch(
        "/api/gear/cell0",
        json={"enhancement_level": 60, "mastery_level": 3},
    )
    assert res.status_code == 200
    body = res.json()["piece"]
    assert body["enhancement_level"] == 60
    assert body["mastery_level"] == 3
    assert body["power"] == compute_gear_power("mythic", 60, 3)
    assert body["icon_url"]

    page = client.get("/gear")
    assert page.status_code == 200
    assert "Judicator" in page.text
    assert "/icons/" in page.text


def test_compute_gear_power_known_anchors() -> None:
    from ks.heroes.ui.power import compute_gear_power

    assert compute_gear_power("blue", 7, None) == 18362
    assert compute_gear_power("green", 6, None) == 11156
    assert compute_gear_power("mythic", 51, 2) == 152100
