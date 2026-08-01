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

    raw = json.loads((tmp_path / "gear.json").read_text(encoding="utf-8"))
    assert raw["gear"][0]["enhancement_level"] == 55

    reloaded = GearStore(tmp_path)
    piece = next(p for p in reloaded.all_pieces() if p.piece_id == "cell0")
    assert piece.enhancement_level == 55


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

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.patch(
        "/api/gear/cell0",
        json={"enhancement_level": 60, "mastery_level": 3},
    )
    assert res.status_code == 200
    assert res.json()["piece"]["enhancement_level"] == 60
    assert res.json()["piece"]["mastery_level"] == 3

    page = client.get("/gear")
    assert page.status_code == 200
    assert "Judicator" in page.text
