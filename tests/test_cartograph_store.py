"""Tests for capture-local cartograph SQLite store."""

from __future__ import annotations

from pathlib import Path

from ks.cartograph.h3_index import default_crs_for_center
from ks.cartograph.render_map import MapEntity
from ks.cartograph.store import count_ui_pins, load_crs, open_capture_db, write_capture_db


def test_write_capture_db_stores_tiles_entities_and_h3(tmp_path: Path) -> None:
    crs = default_crs_for_center(1116, 287, kingdom="2379")
    tiles = [
        {
            "x": 1116,
            "y": 287,
            "covered": True,
            "terrain": "unknown",
            "sampled_rgb": [10, 20, 30],
            "pixel_center": [4.0, 4.0],
            "polygon": [[4.0, 3.0], [6.0, 4.0], [4.0, 5.0], [2.0, 4.0]],
        },
        {
            "x": 1117,
            "y": 287,
            "covered": True,
            "terrain": "unknown",
            "sampled_rgb": [1, 2, 3],
            "pixel_center": [6.0, 5.0],
            "polygon": [[6.0, 4.0], [8.0, 5.0], [6.0, 6.0], [4.0, 5.0]],
        },
    ]
    entities = [
        MapEntity(
            kind="city",
            x=1116,
            y=287,
            label="lord1",
            level=8,
            w=2,
            h=2,
            identity="lord1",
            confidence=0.9,
            provenance="ocr_projected",
            source_frames=("c0_center",),
        ),
        MapEntity(
            kind="rss",
            x=1117,
            y=287,
            label="Farm",
            level=3,
            confidence=0.5,
            provenance="visual_projected",
            source_frames=("g_1_0",),
        ),
        MapEntity(
            kind="unknown",
            x=1118,
            y=288,
            label="unknown",
            confidence=0.4,
            provenance="visual_projected",
        ),
    ]
    db_path = tmp_path / "cartograph.sqlite"
    write_capture_db(
        db_path,
        kingdom="2379",
        center=(1116, 287),
        matrix=((100.0, -100.0), (-80.0, -80.0)),
        crs=crs,
        tiles=tiles,
        entities=entities,
        panorama_size=(100, 80),
        registration={"metrics": {"median_px": 0.1}},
    )

    conn = open_capture_db(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 3
        assert count_ui_pins(conn) == 1
        loaded = load_crs(conn)
        assert loaded.origin_tile_x == 1116
        city = conn.execute(
            "SELECT kind, ui_pin, h3_res9, h3_res7 FROM entities WHERE kind='city'"
        ).fetchone()
        assert city["ui_pin"] == 1
        assert city["h3_res9"]
        assert city["h3_res7"]
        rss = conn.execute(
            "SELECT ui_pin FROM entities WHERE kind='rss'"
        ).fetchone()
        assert rss["ui_pin"] == 0
        tile = conn.execute(
            "SELECT h3_res9 FROM tiles WHERE tile_x=1116 AND tile_y=287"
        ).fetchone()
        assert tile["h3_res9"]
    finally:
        conn.close()
