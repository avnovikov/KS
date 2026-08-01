"""Persist gear inventory to gear.json and gear.db."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ks.heroes.gear_models import GearRecord


class GearStore:
    """Persist gear pieces under out_dir."""

    def __init__(self, out_dir: Path) -> None:
        if not isinstance(out_dir, Path):
            raise TypeError(f"out_dir must be Path; got {type(out_dir).__name__}")
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.out_dir / "gear.json"
        self.db_path = self.out_dir / "gear.db"
        self.details_dir = self.out_dir / "details"
        self._pieces: dict[str, GearRecord] = {}
        self._init_db()
        self._load_existing_json()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gear (
                    piece_id TEXT PRIMARY KEY,
                    name TEXT,
                    troop_type TEXT,
                    slot TEXT,
                    rarity TEXT,
                    enhancement_level INTEGER,
                    mastery_level INTEGER,
                    power INTEGER,
                    equipped INTEGER,
                    equipped_hero TEXT,
                    inventory_page INTEGER NOT NULL,
                    inventory_index INTEGER NOT NULL,
                    scraped_at TEXT,
                    detail_screenshot TEXT,
                    raw_text TEXT
                );
                CREATE TABLE IF NOT EXISTS gear_stats (
                    piece_id TEXT NOT NULL,
                    section TEXT NOT NULL,
                    label TEXT NOT NULL,
                    value REAL NOT NULL,
                    PRIMARY KEY (piece_id, section, label),
                    FOREIGN KEY (piece_id) REFERENCES gear(piece_id)
                );
                """
            )

    def _load_existing_json(self) -> None:
        if not self.json_path.is_file():
            return
        raw = json.loads(self.json_path.read_text(encoding="utf-8"))
        items = raw.get("gear") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        for item in items:
            piece = GearRecord.from_dict(item)
            self._pieces[piece.piece_id] = piece

    def upsert(self, piece: GearRecord) -> None:
        if not piece.piece_id:
            raise ValueError("piece.piece_id must be non-empty")
        self._pieces[piece.piece_id] = piece
        self._write_json()
        self._write_sqlite(piece)

    def all_pieces(self) -> list[GearRecord]:
        return sorted(
            self._pieces.values(),
            key=lambda p: (p.inventory_page, p.inventory_index, p.piece_id),
        )

    def clear(self) -> None:
        """Drop all pieces from memory, JSON, and SQLite (keeps schema)."""
        self._pieces.clear()
        self._write_json()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM gear_stats")
            conn.execute("DELETE FROM gear")

    def reload(self) -> None:
        """Re-read gear.json into memory (picks up external OCR writes)."""
        self._pieces.clear()
        self._load_existing_json()

    def flush(self) -> None:
        self._write_json()
        for piece in self._pieces.values():
            self._write_sqlite(piece)

    def _write_json(self) -> None:
        payload = {"gear": [p.to_dict() for p in self.all_pieces()]}
        self.json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _write_sqlite(self, piece: GearRecord) -> None:
        equipped = None if piece.equipped is None else int(piece.equipped)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO gear (
                    piece_id, name, troop_type, slot, rarity,
                    enhancement_level, mastery_level, power, equipped, equipped_hero,
                    inventory_page, inventory_index, scraped_at, detail_screenshot, raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(piece_id) DO UPDATE SET
                    name=excluded.name,
                    troop_type=excluded.troop_type,
                    slot=excluded.slot,
                    rarity=excluded.rarity,
                    enhancement_level=excluded.enhancement_level,
                    mastery_level=excluded.mastery_level,
                    power=excluded.power,
                    equipped=excluded.equipped,
                    equipped_hero=excluded.equipped_hero,
                    inventory_page=excluded.inventory_page,
                    inventory_index=excluded.inventory_index,
                    scraped_at=excluded.scraped_at,
                    detail_screenshot=excluded.detail_screenshot,
                    raw_text=excluded.raw_text
                """,
                (
                    piece.piece_id,
                    piece.name,
                    piece.troop_type,
                    piece.slot,
                    piece.rarity,
                    piece.enhancement_level,
                    piece.mastery_level,
                    piece.power,
                    equipped,
                    piece.equipped_hero,
                    piece.inventory_page,
                    piece.inventory_index,
                    piece.scraped_at,
                    piece.detail_screenshot,
                    piece.raw_text,
                ),
            )
            conn.execute("DELETE FROM gear_stats WHERE piece_id = ?", (piece.piece_id,))
            if piece.stats:
                for label, value in piece.stats.conquest.items():
                    conn.execute(
                        "INSERT INTO gear_stats (piece_id, section, label, value) VALUES (?, ?, ?, ?)",
                        (piece.piece_id, "conquest", label, float(value)),
                    )
                for label, value in piece.stats.expedition.items():
                    conn.execute(
                        "INSERT INTO gear_stats (piece_id, section, label, value) VALUES (?, ?, ?, ?)",
                        (piece.piece_id, "expedition", label, float(value)),
                    )
