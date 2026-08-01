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
    assert updated.power is not None and updated.power < 152100


def test_create_app_does_not_rewrite_ocr_power(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

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
            power=1,  # stale OCR — must not be rewritten on open
        )
    )
    client = TestClient(create_app(tmp_path))
    body = client.get("/api/gear").json()["gear"][0]
    assert body["power"] == 1


def test_fastapi_clear_enhancement_and_mastery(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.patch(
        "/api/gear/cell0",
        json={"clear_enhancement": True, "clear_mastery": True},
    )
    assert res.status_code == 200
    piece = res.json()["piece"]
    assert piece["enhancement_level"] is None
    assert piece["mastery_level"] is None
    # No rarity+enhancement → power left as last stored value
    assert piece["power"] == 152100


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
    assert "/static/gear-pieces/" in page.text


def test_compute_gear_power_known_anchors() -> None:
    from ks.heroes.ui.power import compute_gear_power, estimate_enhancement_from_power

    assert compute_gear_power("blue", 7, None) == 18362
    assert compute_gear_power("green", 6, None) == 11156
    assert compute_gear_power("mythic", 51, 2) == 152100
    assert estimate_enhancement_from_power("mythic", 152100, 2) == 51
    assert estimate_enhancement_from_power("mythic", 152100, None) == 51
    assert estimate_enhancement_from_power("blue", 18362, None) == 7


def test_gear_store_clear(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    assert len(store.all_pieces()) == 1
    store.clear()
    assert store.all_pieces() == []
    raw = json.loads((tmp_path / "gear.json").read_text(encoding="utf-8"))
    assert raw["gear"] == []
    reloaded = GearStore(tmp_path)
    assert reloaded.all_pieces() == []


def test_gear_store_reload_picks_up_external_json(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    other = GearStore(tmp_path)
    other.clear()
    other.upsert(
        GearRecord(
            piece_id="cell9",
            name="External Piece",
            inventory_page=0,
            inventory_index=9,
        )
    )
    assert len(store.all_pieces()) == 1  # still stale in-memory
    store.reload()
    pieces = store.all_pieces()
    assert len(pieces) == 1
    assert pieces[0].name == "External Piece"


def test_fastapi_rescan_replaces_inventory(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    (tmp_path / "icons").mkdir(exist_ok=True)
    stale_icon = tmp_path / "icons" / "stale.png"
    stale_icon.write_bytes(b"stale")

    def fake_rescan(store: GearStore, **_kwargs: object) -> list[GearRecord]:
        store.clear()
        piece = GearRecord(
            piece_id="cell1",
            name="Scout's Cap",
            troop_type="infantry",
            slot="helmet",
            rarity="blue",
            enhancement_level=7,
            mastery_level=None,
            power=18362,
            inventory_page=0,
            inventory_index=1,
        )
        store.upsert(piece)
        return [piece]

    client = TestClient(create_app(tmp_path, rescan_fn=fake_rescan))
    page = client.get("/gear")
    assert page.status_code == 200
    assert "Rescan from OCR" in page.text
    assert page.headers.get("cache-control") == "no-store"
    assert "?v=" in page.text

    res = client.post("/api/gear/rescan")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["cache_bust"]
    assert body["gear"][0]["name"] == "Scout's Cap"
    assert "v=" in (body["gear"][0].get("icon_url") or "")
    assert not stale_icon.exists()

    listed = client.get("/api/gear").json()["gear"]
    assert len(listed) == 1
    assert listed[0]["piece_id"] == "cell1"
    assert "Judicator" not in json.dumps(listed)


def test_rescan_gear_from_ocr_clears_then_collects(tmp_path: Path) -> None:
    from ks.heroes.ui.rescan import rescan_gear_from_ocr

    store = _seed(tmp_path)
    (tmp_path / "details").mkdir(exist_ok=True)
    (tmp_path / "details" / "old.png").write_bytes(b"x")
    (tmp_path / "icons").mkdir(exist_ok=True)
    (tmp_path / "icons" / "old.svg").write_text("<svg/>", encoding="utf-8")

    class _Cfg:
        adb_serial = None

    def load_cfg(_path: Path | None) -> _Cfg:
        return _Cfg()

    def connect(_serial: str | None) -> object:
        return object()

    def collect(_device: object, _cfg: object, s: GearStore) -> list[GearRecord]:
        piece = GearRecord(
            piece_id="p0",
            name="Fresh Piece",
            inventory_page=0,
            inventory_index=0,
        )
        s.upsert(piece)
        return [piece]

    pieces = rescan_gear_from_ocr(
        store,
        load_config_fn=load_cfg,
        connect_fn=connect,
        collect_fn=collect,
    )
    assert len(pieces) == 1
    assert pieces[0].name == "Fresh Piece"
    assert len(store.all_pieces()) == 1
    assert not (tmp_path / "details" / "old.png").exists()
    assert not (tmp_path / "icons" / "old.svg").exists()
