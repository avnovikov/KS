import json
import sqlite3
from pathlib import Path

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.gear_store import GearStore


def _sample() -> GearRecord:
    return GearRecord(
        piece_id="page0-cell0",
        name="Judicator's Armet",
        troop_type="cavalry",
        slot="helmet",
        rarity="mythic",
        enhancement_level=30,
        mastery_level=2,
        power=98550,
        equipped=True,
        stats=GearStats(
            conquest={"Hero Attack": 288},
            expedition={"Cavalry Lethality": 30.6},
            lethality=30.6,
        ),
        inventory_page=0,
        inventory_index=0,
        scraped_at="2026-08-01T12:00:00Z",
        detail_screenshot="details/page0-cell0.png",
    )


def test_gear_store_json_and_sqlite_round_trip(tmp_path: Path):
    store = GearStore(tmp_path)
    store.upsert(_sample())

    raw = json.loads(store.json_path.read_text(encoding="utf-8"))
    assert raw["gear"][0]["name"] == "Judicator's Armet"
    assert raw["gear"][0]["stats"]["lethality"] == 30.6
    assert raw["gear"][0]["detail_screenshot"] == "details/page0-cell0.png"

    reloaded = GearStore(tmp_path)
    pieces = reloaded.all_pieces()
    assert len(pieces) == 1
    assert pieces[0].piece_id == "page0-cell0"
    assert pieces[0].enhancement_level == 30

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT name, rarity, enhancement_level, mastery_level FROM gear WHERE piece_id = ?",
            ("page0-cell0",),
        ).fetchone()
        assert row == ("Judicator's Armet", "mythic", 30, 2)
        stats = conn.execute(
            "SELECT section, label, value FROM gear_stats WHERE piece_id = ? ORDER BY section, label",
            ("page0-cell0",),
        ).fetchall()
        assert ("conquest", "Hero Attack", 288.0) in stats
        assert ("expedition", "Cavalry Lethality", 30.6) in stats


def test_upsert_locks_enhancement_and_mastery(tmp_path: Path):
    """Re-upsert with None enhancement/mastery preserves the locked prior values."""
    store = GearStore(tmp_path)
    store.upsert(_sample())  # enh=30, mastery=2

    incoming = GearRecord(
        piece_id="page0-cell0",
        name="Judicator's Armet",
        rarity="mythic",
        enhancement_level=None,
        mastery_level=None,
        inventory_page=0,
        inventory_index=0,
    )
    stored = store.upsert(incoming)
    assert stored.enhancement_level == 30, "locked enh must be preserved"
    assert stored.mastery_level == 2, "locked mastery must be preserved"

    raw = json.loads(store.json_path.read_text(encoding="utf-8"))
    assert raw["gear"][0]["enhancement_level"] == 30


def test_upsert_overwrite_unlocks_locked_fields(tmp_path: Path):
    """Passing overwrite={'enhancement_level'} allows new value to win."""
    store = GearStore(tmp_path)
    store.upsert(_sample())

    incoming = GearRecord(
        piece_id="page0-cell0",
        rarity="mythic",
        enhancement_level=40,
        mastery_level=None,
        inventory_page=0,
        inventory_index=0,
    )
    stored = store.upsert(incoming, overwrite=frozenset({"enhancement_level"}))
    assert stored.enhancement_level == 40
    # mastery not in overwrite and prior is 2 → preserved
    assert stored.mastery_level == 2


def test_get_returns_none_for_missing(tmp_path: Path):
    store = GearStore(tmp_path)
    assert store.get("nonexistent") is None


def test_get_returns_stored_piece(tmp_path: Path):
    store = GearStore(tmp_path)
    store.upsert(_sample())
    piece = store.get("page0-cell0")
    assert piece is not None
    assert piece.name == "Judicator's Armet"


def test_delete_removes_from_all_backends(tmp_path: Path):
    store = GearStore(tmp_path)
    store.upsert(_sample())
    deleted = store.delete("page0-cell0")
    assert deleted is True
    assert store.get("page0-cell0") is None
    assert len(store.all_pieces()) == 0

    raw = json.loads(store.json_path.read_text(encoding="utf-8"))
    assert raw["gear"] == []

    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute("SELECT * FROM gear WHERE piece_id = ?", ("page0-cell0",)).fetchall()
        assert rows == []
        stats = conn.execute("SELECT * FROM gear_stats WHERE piece_id = ?", ("page0-cell0",)).fetchall()
        assert stats == []


def test_delete_returns_false_for_missing(tmp_path: Path):
    store = GearStore(tmp_path)
    assert store.delete("missing-id") is False


def test_preserve_if_none_for_non_locked_fields(tmp_path: Path):
    """Non-locked fields in _PRESERVE_IF_NONE fall back to prior value when incoming is None."""
    store = GearStore(tmp_path)
    store.upsert(_sample())  # name="Judicator's Armet", troop_type="cavalry"

    incoming = GearRecord(
        piece_id="page0-cell0",
        name=None,
        troop_type=None,
        rarity="mythic",
        enhancement_level=30,
        mastery_level=2,
        inventory_page=0,
        inventory_index=0,
    )
    stored = store.upsert(incoming, overwrite=frozenset({"enhancement_level", "mastery_level"}))
    assert stored.name == "Judicator's Armet", "name preserved from prior"
    assert stored.troop_type == "cavalry", "troop_type preserved from prior"
