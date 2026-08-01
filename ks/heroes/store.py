from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from ks.heroes.models import HeroRecord

# Fields often set by hand / follow-up edits; keep prior value if update leaves them empty.
_PRESERVE_IF_NONE = ("level", "pellets", "stars", "escorts", "power", "rarity", "troop_type")


def _merge_preserved(prev: HeroRecord, incoming: HeroRecord) -> HeroRecord:
    updates = {
        field: getattr(prev, field)
        for field in _PRESERVE_IF_NONE
        if getattr(incoming, field) is None and getattr(prev, field) is not None
    }
    return replace(incoming, **updates) if updates else incoming


class HeroStore:
    """Persist heroes to heroes.json and heroes.db under out_dir."""

    def __init__(self, out_dir: Path) -> None:
        if not isinstance(out_dir, Path):
            raise TypeError(f"out_dir must be Path; got {type(out_dir).__name__}")
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.out_dir / "heroes.json"
        self.db_path = self.out_dir / "heroes.db"
        self.names_dir = self.out_dir / "names"
        self._heroes: dict[str, HeroRecord] = {}
        self._init_db()
        self._load_existing_json()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS heroes (
                    name TEXT PRIMARY KEY,
                    power INTEGER,
                    rarity TEXT,
                    troop_type TEXT,
                    escorts INTEGER,
                    stars INTEGER,
                    pellets INTEGER,
                    roster_page INTEGER NOT NULL,
                    roster_index INTEGER NOT NULL,
                    scraped_at TEXT NOT NULL,
                    name_screenshot TEXT
                );
                CREATE TABLE IF NOT EXISTS hero_stats (
                    hero_name TEXT NOT NULL,
                    section TEXT NOT NULL,
                    label TEXT NOT NULL,
                    value REAL NOT NULL,
                    PRIMARY KEY (hero_name, section, label),
                    FOREIGN KEY (hero_name) REFERENCES heroes(name)
                );
                CREATE TABLE IF NOT EXISTS skills (
                    hero_name TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    name TEXT,
                    level INTEGER,
                    description TEXT,
                    upgrade_preview TEXT,
                    current_bonus REAL,
                    raw_text TEXT,
                    PRIMARY KEY (hero_name, slot),
                    FOREIGN KEY (hero_name) REFERENCES heroes(name)
                );
                """
            )
            skill_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(skills)").fetchall()
            }
            if "current_bonus" not in skill_cols:
                conn.execute("ALTER TABLE skills ADD COLUMN current_bonus REAL")
            hero_cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(heroes)").fetchall()
            }
            if "name_screenshot" not in hero_cols:
                conn.execute("ALTER TABLE heroes ADD COLUMN name_screenshot TEXT")
            if "pellets" not in hero_cols:
                conn.execute("ALTER TABLE heroes ADD COLUMN pellets INTEGER")
            if "level" not in hero_cols:
                conn.execute("ALTER TABLE heroes ADD COLUMN level INTEGER")

    def _load_existing_json(self) -> None:
        if not self.json_path.is_file():
            return
        raw = json.loads(self.json_path.read_text(encoding="utf-8"))
        heroes = raw.get("heroes") if isinstance(raw, dict) else raw
        if not isinstance(heroes, list):
            return
        for item in heroes:
            hero = HeroRecord.from_dict(item)
            self._heroes[hero.name] = hero

    def upsert(self, hero: HeroRecord) -> None:
        if not hero.name:
            raise ValueError("hero.name must be non-empty")
        # Preserve manually curated fields when a partial scrape/update omits them.
        prev = self._heroes.get(hero.name)
        if prev is not None:
            hero = _merge_preserved(prev, hero)
        self._heroes[hero.name] = hero
        self._write_json()
        self._write_sqlite(hero)

    def all_heroes(self) -> list[HeroRecord]:
        return sorted(self._heroes.values(), key=lambda h: (h.roster_page, h.roster_index, h.name))

    def reload(self) -> None:
        """Re-read heroes.json into memory (picks up external OCR writes)."""
        self._heroes.clear()
        self._load_existing_json()

    def flush(self) -> None:
        self._write_json()
        for hero in self._heroes.values():
            self._write_sqlite(hero)

    def _write_json(self) -> None:
        payload = {
            "heroes": [h.to_dict() for h in self.all_heroes()],
        }
        self.json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _write_sqlite(self, hero: HeroRecord) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO heroes (
                    name, power, level, rarity, troop_type, escorts, stars, pellets,
                    roster_page, roster_index, scraped_at, name_screenshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    power=excluded.power,
                    level=excluded.level,
                    rarity=excluded.rarity,
                    troop_type=excluded.troop_type,
                    escorts=excluded.escorts,
                    stars=excluded.stars,
                    pellets=excluded.pellets,
                    roster_page=excluded.roster_page,
                    roster_index=excluded.roster_index,
                    scraped_at=excluded.scraped_at,
                    name_screenshot=excluded.name_screenshot
                """,
                (
                    hero.name,
                    hero.power,
                    hero.level,
                    hero.rarity,
                    hero.troop_type,
                    hero.escorts,
                    hero.stars,
                    hero.pellets,
                    hero.roster_page,
                    hero.roster_index,
                    hero.scraped_at,
                    hero.name_screenshot,
                ),
            )
            conn.execute("DELETE FROM hero_stats WHERE hero_name = ?", (hero.name,))
            conn.execute("DELETE FROM skills WHERE hero_name = ?", (hero.name,))
            if hero.stats:
                for label, value in hero.stats.conquest.items():
                    conn.execute(
                        "INSERT INTO hero_stats (hero_name, section, label, value) VALUES (?, ?, ?, ?)",
                        (hero.name, "conquest", label, float(value)),
                    )
                for label, value in hero.stats.expedition.items():
                    conn.execute(
                        "INSERT INTO hero_stats (hero_name, section, label, value) VALUES (?, ?, ?, ?)",
                        (hero.name, "expedition", label, float(value)),
                    )
            for skill in hero.skills:
                conn.execute(
                    """
                    INSERT INTO skills (
                        hero_name, slot, name, level, description,
                        upgrade_preview, current_bonus, raw_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hero.name,
                        skill.slot,
                        skill.name,
                        skill.level,
                        skill.description,
                        skill.upgrade_preview,
                        skill.current_bonus,
                        skill.raw_text,
                    ),
                )
            conn.commit()
