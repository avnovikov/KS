from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ks.heroes.assurance import FieldAssurance
from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore


def test_store_round_trips_assurance(tmp_path: Path):
    store = HeroStore(tmp_path)
    hero = HeroRecord(
        name="Gordon",
        power=262120,
        stars=3,
        scraped_at="t",
        assurance={"power": FieldAssurance("high", "manual_confirm")},
    )
    store.upsert(hero)
    store2 = HeroStore(tmp_path)
    got = next(h for h in store2.all_heroes() if h.name == "Gordon")
    assert got.assurance["power"].level == "high"
    assert got.assurance["power"].reason == "manual_confirm"
    # stars present without assurance → legacy filled on load
    assert got.assurance["stars"].reason == "legacy_unscored"


def test_hero_record_dict_round_trip():
    h = HeroRecord(
        name="A",
        power=1,
        scraped_at="t",
        assurance={"power": FieldAssurance("medium", "roster_ocr")},
    )
    h2 = HeroRecord.from_dict(h.to_dict())
    assert h2.assurance["power"].level == "medium"


def test_assurance_json_column_added_to_existing_db(tmp_path: Path):
    """ALTER TABLE migration: new store picks up assurance_json on old DB."""
    store = HeroStore(tmp_path)
    hero = HeroRecord(
        name="OldHero",
        power=100,
        scraped_at="t",
        assurance={"level": FieldAssurance("low", "ocr_guess")},
    )
    store.upsert(hero)
    store2 = HeroStore(tmp_path)
    got = next(h for h in store2.all_heroes() if h.name == "OldHero")
    assert got.assurance["level"].level == "low"


def test_no_assurance_hero_gets_empty_dict(tmp_path: Path):
    store = HeroStore(tmp_path)
    hero = HeroRecord(name="Plain", power=50, scraped_at="t")
    store.upsert(hero)
    store2 = HeroStore(tmp_path)
    got = next(h for h in store2.all_heroes() if h.name == "Plain")
    assert isinstance(got.assurance, dict)
    # power is present → legacy fill
    assert got.assurance["power"].reason == "legacy_unscored"


def test_upsert_applies_legacy_assurance_before_persisting(tmp_path: Path):
    store = HeroStore(tmp_path)
    hero = HeroRecord(
        name="Gordon",
        power=262120,
        stars=3,
        scraped_at="t",
        assurance={},
    )

    stored = store.upsert(hero)

    assert stored.assurance["power"].reason == "legacy_unscored"
    assert stored.assurance["power"].level == "medium"
    assert stored.assurance["stars"].reason == "legacy_unscored"
    assert stored.assurance["stars"].level == "medium"
    assert "level" not in stored.assurance
    assert "pellets" not in stored.assurance

    in_memory = next(h for h in store.all_heroes() if h.name == "Gordon")
    assert in_memory.assurance == stored.assurance

    payload = json.loads((tmp_path / "heroes.json").read_text(encoding="utf-8"))
    saved = next(h for h in payload["heroes"] if h["name"] == "Gordon")
    assert saved["assurance"]["power"]["reason"] == "legacy_unscored"
    assert saved["assurance"]["stars"]["reason"] == "legacy_unscored"
    assert "level" not in saved["assurance"]
    assert "pellets" not in saved["assurance"]

    with sqlite3.connect(tmp_path / "heroes.db") as conn:
        (assurance_json,) = conn.execute(
            "SELECT assurance_json FROM heroes WHERE name = ?",
            ("Gordon",),
        ).fetchone()
    persisted = json.loads(assurance_json)
    assert persisted["power"]["reason"] == "legacy_unscored"
    assert persisted["stars"]["reason"] == "legacy_unscored"
