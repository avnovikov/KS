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
