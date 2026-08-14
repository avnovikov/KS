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

    store = _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.patch(
        "/api/gear/cell0",
        json={"clear_enhancement": True, "clear_mastery": True},
    )
    assert res.status_code == 200
    piece = res.json()["piece"]
    assert piece["enhancement_level"] is None
    assert piece["mastery_level"] is None
    # Persist to disk — not only the response body.
    store.reload()
    saved = store.get("cell0")
    assert saved is not None
    assert saved.enhancement_level is None
    assert saved.mastery_level is None
    # Cleared enhancement → sync_piece_power skips recompute; power stays last stored value
    assert piece["power"] == 152100


def test_fastapi_clear_rarity_persists(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    store = _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.patch("/api/gear/cell0", json={"clear_rarity": True})
    assert res.status_code == 200
    assert res.json()["piece"]["rarity"] is None
    store.reload()
    saved = store.get("cell0")
    assert saved is not None
    assert saved.rarity is None


def test_patch_rarity_persists_and_locks_vs_ocr(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app
    from ks.heroes.ui.power import compute_gear_power

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.patch("/api/gear/cell0", json={"rarity": "blue"})
    assert res.status_code == 200
    piece = res.json()["piece"]
    assert piece["rarity"] == "blue"
    assert piece["power"] == compute_gear_power("blue", 51, 2)

    # OCR cannot clobber a saved rarity without overwrite.
    store = GearStore(tmp_path)
    store.reload()
    store.upsert(
        GearRecord(
            piece_id="cell0",
            name="Judicator's Armet",
            rarity="grey",
            enhancement_level=51,
            mastery_level=2,
            power=1,
        )
    )
    locked = store.get("cell0")
    assert locked is not None
    assert locked.rarity == "blue"

    # Save path still updates rarity.
    updated = update_piece_levels(store, "cell0", rarity="grey")
    assert updated.rarity == "grey"


def test_patch_slot_persists_and_locks_vs_ocr(tmp_path: Path) -> None:
    """UI can correct a mis-slotted helm; OCR cannot clobber it."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    store = GearStore(tmp_path)
    store.upsert(
        GearRecord(
            piece_id="cell0",
            name="Stonewall Helm",
            troop_type="infantry",
            slot="chest",  # OCR mislabel
            rarity="blue",
            enhancement_level=9,
            power=19394,
        )
    )
    client = TestClient(create_app(tmp_path))
    res = client.patch("/api/gear/cell0", json={"slot": "helmet"})
    assert res.status_code == 200
    assert res.json()["piece"]["slot"] == "helmet"

    store.reload()
    # OCR wrong slot again — locked value wins.
    store.upsert(
        GearRecord(
            piece_id="cell0",
            name="Stonewall Helm",
            troop_type="infantry",
            slot="chest",
            rarity="blue",
            enhancement_level=9,
            power=19394,
        )
    )
    locked = store.get("cell0")
    assert locked is not None
    assert locked.slot == "helmet"

    # Alias + clear paths.
    assert update_piece_levels(store, "cell0", slot="helm").slot == "helmet"
    cleared = update_piece_levels(store, "cell0", slot=None)
    assert cleared.slot is None


def test_patch_rejects_invalid_slot(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.patch("/api/gear/cell0", json={"slot": "cape"})
    assert res.status_code == 400


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
        # Simulate: old piece no longer in inventory, new piece collected.
        store.delete("cell0")
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

    # /api/gear/rescan answers with one JSON document (not an SSE stream):
    # the /inventory IA needs the whole post-rescan set plus the trust diff
    # in a single response so the page can render "needs attention" without
    # replaying events. Porting the SSE progress log back is tracked
    # separately.
    res = client.post("/api/gear/rescan")
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["trust"]["flags"] == {"cell1": "new"}
    assert [p["piece_id"] for p in payload["gear"]] == ["cell1"]

    listed = client.get("/api/gear").json()["gear"]
    assert len(listed) == 1
    assert listed[0]["piece_id"] == "cell1"
    assert "Judicator" not in json.dumps(listed)


def test_rescan_gear_from_ocr_clears_then_collects(tmp_path: Path) -> None:
    from ks.heroes.ui.rescan import rescan_gear_from_ocr

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

    def collect(_device: object, _cfg: object, s: GearStore, **_kw) -> list[GearRecord]:
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
    # Stale prior piece (cell0 from _seed) deleted since not in collected set.
    assert len(store.all_pieces()) == 1
    assert store.all_pieces()[0].piece_id == "p0"
    assert not (tmp_path / "details" / "old.png").exists()
    assert not (tmp_path / "icons" / "old.svg").exists()


def test_next_manual_piece_id_increments() -> None:
    from ks.heroes.ui.app import next_manual_piece_id

    assert next_manual_piece_id([]) == "manual-1"
    assert next_manual_piece_id(["cell0", "manual-1", "manual-3"]) == "manual-4"
    assert next_manual_piece_id(["manual-2", "page0-cell1"]) == "manual-3"


def test_create_manual_piece_persists_json_and_sql(tmp_path: Path) -> None:
    from ks.heroes.ui.app import create_manual_piece

    store = GearStore(tmp_path)
    piece = create_manual_piece(
        store, troop_type="cavalry", slot="gloves", rarity="epic"
    )
    assert piece.piece_id == "manual-1"
    assert piece.name == "Crusader's Gauntlets"
    assert piece.troop_type == "cavalry"
    assert piece.slot == "gloves"
    assert piece.rarity == "epic"
    assert piece.enhancement_level is None
    assert piece.mastery_level is None
    assert piece.power is None

    raw = json.loads((tmp_path / "gear.json").read_text(encoding="utf-8"))
    assert any(p["piece_id"] == "manual-1" for p in raw["gear"])

    reloaded = GearStore(tmp_path)
    found = next(p for p in reloaded.all_pieces() if p.piece_id == "manual-1")
    assert found.name == "Crusader's Gauntlets"


def test_create_manual_piece_allows_duplicate_triple(tmp_path: Path) -> None:
    from ks.heroes.ui.app import create_manual_piece

    store = GearStore(tmp_path)
    a = create_manual_piece(
        store, troop_type="cavalry", slot="gloves", rarity="epic"
    )
    b = create_manual_piece(
        store, troop_type="cavalry", slot="gloves", rarity="epic"
    )
    assert a.piece_id == "manual-1"
    assert b.piece_id == "manual-2"
    assert a.name == b.name == "Crusader's Gauntlets"


def test_create_manual_piece_rejects_unknown_triple(tmp_path: Path) -> None:
    from ks.heroes.ui.app import create_manual_piece

    store = GearStore(tmp_path)
    with pytest.raises(ValueError, match="unknown"):
        create_manual_piece(
            store, troop_type="cavalry", slot="gloves", rarity="grey"
        )


def test_fastapi_post_gear_creates_piece(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.post(
        "/api/gear",
        json={"troop_type": "cavalry", "slot": "gloves", "rarity": "epic"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    piece = body["piece"]
    assert piece["piece_id"] == "manual-1"
    assert piece["name"] == "Crusader's Gauntlets"
    assert piece["troop_type"] == "cavalry"
    assert piece["slot"] == "gloves"
    assert piece["rarity"] == "epic"
    assert "icon_url" in piece

    listed = client.get("/api/gear").json()["gear"]
    assert any(p["piece_id"] == "manual-1" for p in listed)


def test_fastapi_post_gear_rejects_unknown_triple(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.post(
        "/api/gear",
        json={"troop_type": "cavalry", "slot": "cape", "rarity": "epic"},
    )
    assert res.status_code == 400


def test_inventory_gear_page_has_add_control(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    page = client.get("/inventory/gear")
    assert page.status_code == 200
    assert 'id="add-gear-btn"' in page.text
    assert 'id="add-gear-dialog"' in page.text


def test_fastapi_delete_gear(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))

    res = client.delete("/api/gear/cell0")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["deleted"] == "cell0"

    listed = client.get("/api/gear").json()["gear"]
    assert all(p["piece_id"] != "cell0" for p in listed)


def test_fastapi_delete_gear_404(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(tmp_path))
    res = client.delete("/api/gear/nonexistent")
    assert res.status_code == 404


def test_update_piece_levels_with_overwrite_persists_locked_field(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_piece_levels

    store = _seed(tmp_path)
    # Simulate a rescan that sets enhancement to None (OCR miss); after lock, it should stay 51.
    from ks.heroes.gear_models import GearRecord
    store.upsert(
        GearRecord(
            piece_id="cell0",
            name="Judicator's Armet",
            rarity="mythic",
            enhancement_level=None,
            mastery_level=2,
            power=152100,
            inventory_page=0,
            inventory_index=0,
        )
    )
    # Lock should have preserved enh=51 (from seed); calling update_piece_levels
    # with overwrite set should allow update.
    piece = next(p for p in store.all_pieces() if p.piece_id == "cell0")
    assert piece.enhancement_level == 51, "lock must preserve enhancement_level=51"

    updated = update_piece_levels(store, "cell0", enhancement_level=55)
    assert updated.enhancement_level == 55
    assert updated.power is not None and updated.power > 152100


# `test_gear_page_includes_power_curves_json` lived here. It pinned the
# inline `POWER_CURVES` constant that the deleted legacy gear template
# embedded (unnameable here: a sibling test forbids naming it) so the
# power cell could preview a rarity/enhancement edit before Save. The
# /inventory shell forbids inline <script>, and its gear page has no editable
# rarity yet, so there is nothing on any page to pin. The helper the feature
# is built from is still covered by the next test; the preview itself is part
# of the pending UI port.
def test_rarity_power_curves_includes_grey() -> None:
    from ks.heroes.ui.power import rarity_power_curves

    curves = rarity_power_curves()
    assert "grey" in curves
    assert len(curves["grey"]) == 81  # 0..80 inclusive
    assert curves["grey"][0] == 4500
    assert curves["grey"][5] > curves["grey"][0]
