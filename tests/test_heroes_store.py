import json
import sqlite3
from pathlib import Path

from ks.heroes.models import HeroRecord, HeroStats, SkillRecord
from ks.heroes.store import HeroStore


def _sample() -> HeroRecord:
    return HeroRecord(
        name="Jabel",
        power=123456,
        rarity="SSR",
        troop_type="Cavalry",
        escorts=8,
        stars=1,
        stats=HeroStats(
            conquest={"Hero Attack": 1619},
            expedition={"Cavalry Attack": 101.37},
        ),
        skills=(
            SkillRecord(
                slot=0,
                name="Rally Flag",
                level=3,
                description="24% chance",
                current_bonus=24.0,
            ),
        ),
        roster_page=0,
        roster_index=0,
        scraped_at="2026-08-01T12:00:00Z",
    )


def test_hero_store_json_and_sqlite_round_trip(tmp_path: Path):
    store = HeroStore(tmp_path)
    store.upsert(_sample())

    raw = json.loads(store.json_path.read_text(encoding="utf-8"))
    assert raw["heroes"][0]["name"] == "Jabel"
    assert raw["heroes"][0]["stats"]["conquest"]["Hero Attack"] == 1619

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT power, rarity, escorts FROM heroes WHERE name = ?", ("Jabel",)
        ).fetchone()
        assert row == (123456, "SSR", 8)
        skills = conn.execute(
            "SELECT name, level, current_bonus FROM skills WHERE hero_name = ?",
            ("Jabel",),
        ).fetchall()
        assert skills == [("Rally Flag", 3, 24.0)]
        assert raw["heroes"][0]["skills"][0]["current_bonus"] == 24.0
        stats = conn.execute(
            "SELECT section, label, value FROM hero_stats WHERE hero_name = ? ORDER BY section, label",
            ("Jabel",),
        ).fetchall()
        assert ("conquest", "Hero Attack", 1619.0) in stats
        assert ("expedition", "Cavalry Attack", 101.37) in stats
