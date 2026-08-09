"""Tests for GovernorGearStore persistence and upgrade."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.governor_models import GovernorPiece
from ks.heroes.governor_store import GovernorGearStore

ROOT = Path(__file__).resolve().parents[1]


def test_store_defaults_six_slots_and_upgrade(tmp_path: Path) -> None:
    store = GovernorGearStore(tmp_path, config_path=ROOT / "config" / "governor_gear.yaml")
    assert len(store.all_pieces()) == 6
    hood = store.get("hood")
    assert hood is not None
    assert hood.tier == "green"
    assert hood.stars == 0
    bumped = store.upgrade("hood")
    assert bumped.stars == 1
    assert bumped.attack_pct == pytest.approx(12.75)
    reloaded = GovernorGearStore(tmp_path, config_path=ROOT / "config" / "governor_gear.yaml")
    assert reloaded.get("hood") is not None
    assert reloaded.get("hood").stars == 1
    # sqlite row present
    import sqlite3

    with sqlite3.connect(tmp_path / "governor_gear.db") as conn:
        row = conn.execute(
            "select tier, stars from governor_gear where slot_id='hood'"
        ).fetchone()
    assert row == ("green", 1)


def test_upsert_rejects_unknown_slot(tmp_path: Path) -> None:
    store = GovernorGearStore(tmp_path, config_path=ROOT / "config" / "governor_gear.yaml")
    with pytest.raises(KeyError):
        store.upsert(GovernorPiece(slot_id="hat", tier="green", stars=0))
