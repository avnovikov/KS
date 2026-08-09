"""Persist governor gear to governor_gear.json and governor_gear.db."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ks.heroes.governor_bonuses import enrich_piece, governor_troop_bonuses
from ks.heroes.governor_config import (
    GovernorGearConfig,
    load_governor_gear_config,
    next_ladder_step,
)
from ks.heroes.governor_models import GovernorPiece, GovernorTroopBonuses


class GovernorGearStore:
    """Six-slot governor gear inventory under ``out_dir``."""

    def __init__(
        self,
        out_dir: Path,
        *,
        config: GovernorGearConfig | None = None,
        config_path: Path | None = None,
    ) -> None:
        if not isinstance(out_dir, Path):
            raise TypeError(f"out_dir must be Path; got {type(out_dir).__name__}")
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.out_dir / "governor_gear.json"
        self.db_path = self.out_dir / "governor_gear.db"
        self.cfg = config or load_governor_gear_config(config_path)
        self._pieces: dict[str, GovernorPiece] = {}
        self._init_db()
        self._load_existing_json()
        self.ensure_defaults()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS governor_gear (
                    slot_id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    stars INTEGER NOT NULL,
                    attack_pct REAL NOT NULL,
                    defense_pct REAL NOT NULL,
                    power INTEGER NOT NULL
                );
                """
            )

    def _load_existing_json(self) -> None:
        if not self.json_path.is_file():
            return
        raw = json.loads(self.json_path.read_text(encoding="utf-8"))
        items = raw.get("pieces") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            raise ValueError(
                f"{self.json_path} must be a list or {{'pieces': [...]}}"
            )
        for item in items:
            piece = GovernorPiece.from_dict(item)
            self._pieces[piece.slot_id] = enrich_piece(piece, self.cfg)

    def ensure_defaults(self) -> None:
        """Create missing slots at default ladder step and persist if needed."""
        dirty = False
        for slot_id in self.cfg.slots:
            if slot_id in self._pieces:
                continue
            piece = enrich_piece(
                GovernorPiece(
                    slot_id=slot_id,
                    tier=self.cfg.default_tier,
                    stars=self.cfg.default_stars,
                ),
                self.cfg,
            )
            self._pieces[slot_id] = piece
            dirty = True
        if dirty:
            self.flush()

    def get(self, slot_id: str) -> GovernorPiece | None:
        return self._pieces.get(slot_id)

    def all_pieces(self) -> list[GovernorPiece]:
        return [self._pieces[s] for s in self.cfg.slots if s in self._pieces]

    def upsert(self, piece: GovernorPiece) -> GovernorPiece:
        if piece.slot_id not in self.cfg.slots:
            raise KeyError(f"unknown governor slot {piece.slot_id!r}")
        enriched = enrich_piece(piece, self.cfg)
        self._pieces[enriched.slot_id] = enriched
        self._write_json()
        self._write_sqlite(enriched)
        return enriched

    def upgrade(self, slot_id: str) -> GovernorPiece:
        prev = self._pieces.get(slot_id)
        if prev is None:
            raise KeyError(f"missing governor slot {slot_id!r}")
        nxt = next_ladder_step(self.cfg, prev.tier, prev.stars)
        if nxt is None:
            raise ValueError(f"governor slot {slot_id!r} is already at max ladder step")
        return self.upsert(
            GovernorPiece(slot_id=slot_id, tier=nxt.tier, stars=nxt.stars)
        )

    def bonuses(self) -> GovernorTroopBonuses:
        return governor_troop_bonuses(self.all_pieces(), self.cfg)

    def summary(self) -> dict:
        bonuses = self.bonuses()
        return {
            "pieces": [
                {
                    **p.to_dict(),
                    "display_name": self.cfg.slots[p.slot_id].display_name,
                    "troop": self.cfg.slots[p.slot_id].troop,
                }
                for p in self.all_pieces()
            ],
            "bonuses": bonuses.to_dict(),
        }

    def flush(self) -> None:
        self._write_json()
        for piece in self.all_pieces():
            self._write_sqlite(piece)

    def _write_json(self) -> None:
        payload = {"pieces": [p.to_dict() for p in self.all_pieces()]}
        self.json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _write_sqlite(self, piece: GovernorPiece) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO governor_gear (
                    slot_id, tier, stars, attack_pct, defense_pct, power
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slot_id) DO UPDATE SET
                    tier=excluded.tier,
                    stars=excluded.stars,
                    attack_pct=excluded.attack_pct,
                    defense_pct=excluded.defense_pct,
                    power=excluded.power
                """,
                (
                    piece.slot_id,
                    piece.tier,
                    piece.stars,
                    piece.attack_pct,
                    piece.defense_pct,
                    piece.power,
                ),
            )
