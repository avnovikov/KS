"""Capture-local SQLite persistence for diamond tiles and entities."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ks.cartograph.h3_index import (
    KingdomCrs,
    assert_round_trip_sample,
    game_tile_to_h3,
    is_ui_pin_kind,
)
from ks.cartograph.render_map import MapEntity

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY,
    kingdom TEXT NOT NULL,
    center_x INTEGER NOT NULL,
    center_y INTEGER NOT NULL,
    matrix_json TEXT NOT NULL,
    panorama_width INTEGER,
    panorama_height INTEGER,
    registration_json TEXT,
    crs_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiles (
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    covered INTEGER NOT NULL,
    terrain TEXT NOT NULL,
    sampled_rgb_json TEXT,
    pixel_center_json TEXT,
    polygon_json TEXT,
    h3_res9 TEXT NOT NULL,
    PRIMARY KEY (tile_x, tile_y)
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT,
    identity TEXT,
    level INTEGER,
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    w INTEGER NOT NULL,
    h INTEGER NOT NULL,
    world_x REAL,
    world_y REAL,
    confidence REAL,
    provenance TEXT NOT NULL,
    source_frames_json TEXT,
    coordinate_residual_px REAL,
    popup_path TEXT,
    h3_res9 TEXT NOT NULL,
    h3_res7 TEXT,
    ui_pin INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tiles_h3_res9 ON tiles(h3_res9);
CREATE INDEX IF NOT EXISTS idx_entities_h3_res9 ON entities(h3_res9);
CREATE INDEX IF NOT EXISTS idx_entities_h3_res7 ON entities(h3_res7);
CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entities_ui_pin ON entities(ui_pin);
CREATE INDEX IF NOT EXISTS idx_entities_tile ON entities(tile_x, tile_y);
"""


@dataclass(frozen=True)
class TileRecord:
    tile_x: int
    tile_y: int
    covered: bool
    terrain: str
    sampled_rgb: list[int] | None
    pixel_center: list[float] | None
    polygon: list[list[float]] | None
    h3_res9: str


def write_capture_db(
    path: Path,
    *,
    kingdom: str,
    center: tuple[int, int],
    matrix: Sequence[Sequence[float]],
    crs: KingdomCrs,
    tiles: Sequence[Mapping[str, Any]],
    entities: Sequence[MapEntity],
    panorama_size: tuple[int, int] | None = None,
    registration: Mapping[str, Any] | None = None,
    round_trip_radius: int = 8,
) -> Path:
    """Replace ``path`` with a fresh capture database. Diamond coords are primary."""
    if not kingdom:
        raise ValueError("kingdom must be non-empty")
    assert_round_trip_sample(crs, radius=round_trip_radius)

    path = Path(path)
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        width = height = None
        if panorama_size is not None:
            width, height = int(panorama_size[0]), int(panorama_size[1])
        conn.execute(
            """
            INSERT INTO captures (
                kingdom, center_x, center_y, matrix_json,
                panorama_width, panorama_height, registration_json, crs_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kingdom,
                int(center[0]),
                int(center[1]),
                json.dumps([list(row) for row in matrix]),
                width,
                height,
                None if registration is None else json.dumps(registration),
                json.dumps(crs.to_json()),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        tile_rows = []
        for tile in tiles:
            tx, ty = int(tile["x"]), int(tile["y"])
            h3_cell = game_tile_to_h3(
                kingdom, tx, ty, crs=crs, res=crs.h3_detail_res
            )
            tile_rows.append(
                (
                    tx,
                    ty,
                    1 if tile.get("covered", True) else 0,
                    str(tile.get("terrain") or "unknown"),
                    _json_or_none(tile.get("sampled_rgb")),
                    _json_or_none(tile.get("pixel_center")),
                    _json_or_none(tile.get("polygon")),
                    h3_cell,
                )
            )
        conn.executemany(
            """
            INSERT INTO tiles (
                tile_x, tile_y, covered, terrain, sampled_rgb_json,
                pixel_center_json, polygon_json, h3_res9
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tile_rows,
        )

        entity_rows = []
        for entity in entities:
            h3_detail = game_tile_to_h3(
                kingdom, entity.x, entity.y, crs=crs, res=crs.h3_detail_res
            )
            h3_region = game_tile_to_h3(
                kingdom, entity.x, entity.y, crs=crs, res=crs.h3_region_res
            )
            entity_rows.append(
                (
                    entity.kind,
                    entity.label,
                    entity.identity,
                    entity.level,
                    entity.x,
                    entity.y,
                    entity.w,
                    entity.h,
                    None,
                    None,
                    entity.confidence,
                    entity.provenance or "unknown",
                    json.dumps(list(entity.source_frames)),
                    entity.coordinate_residual_px,
                    entity.popup_path,
                    h3_detail,
                    h3_region,
                    1 if is_ui_pin_kind(entity.kind) else 0,
                )
            )
        conn.executemany(
            """
            INSERT INTO entities (
                kind, label, identity, level, tile_x, tile_y, w, h,
                world_x, world_y, confidence, provenance, source_frames_json,
                coordinate_residual_px, popup_path, h3_res9, h3_res7, ui_pin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            entity_rows,
        )
        conn.commit()
    finally:
        conn.close()
    return path


def open_capture_db(path: Path) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise FileNotFoundError(f"capture database not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def load_crs(conn: sqlite3.Connection) -> KingdomCrs:
    row = conn.execute(
        "SELECT crs_json FROM captures ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("captures table is empty")
    return KingdomCrs.from_json(json.loads(row["crs_json"]))


def count_ui_pins(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM entities WHERE ui_pin = 1"
    ).fetchone()
    return int(row["n"])


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)
