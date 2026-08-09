"""Tests for Radiant stage·round opponent YAML store."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.optimize.mystic_trial.radiant_opponents import (
    get_stage_round,
    load_store,
    merge_saved_into_opponent,
    opponents_path,
    parse_march,
    ratio_from_counts,
    save_store,
    upsert_march,
)


def test_opponents_path_under_governor(tmp_path: Path) -> None:
    assert opponents_path(tmp_path) == tmp_path / "mystic_trial" / "radiant_opponents.yaml"


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    store = load_store(tmp_path / "missing.yaml")
    assert store["stages"] == {}
    assert store["version"] == 1


def test_upsert_slot_round_trips(tmp_path: Path) -> None:
    path = opponents_path(tmp_path)
    store = load_store(path)
    march = parse_march(
        {
            "levels": {"infantry": 7, "cavalry": 6, "archers": 6},
            "counts": {"infantry": 42000, "cavalry": 18000, "archers": 15000},
            "bonuses": {
                "infantry": {"attack_pct": 120, "defense_pct": 80},
            },
        }
    )
    store = upsert_march(store, stage=3, round_no=2, slot=0, march=march)
    save_store(path, store)

    again = load_store(path)
    marches = get_stage_round(again, 3, 2)
    assert marches is not None
    assert marches[0]["levels"]["infantry"] == 7
    assert marches[0]["counts"]["infantry"] == 42000
    assert marches[0]["bonuses"]["infantry"]["attack_pct"] == 120.0
    assert marches[1]["counts"]["infantry"] == 0  # second slot defaulted


def test_upsert_slots_independent(tmp_path: Path) -> None:
    store = load_store(tmp_path / "x.yaml")
    store = upsert_march(
        store,
        stage=1,
        round_no=1,
        slot=0,
        march=parse_march({"counts": {"infantry": 10, "cavalry": 0, "archers": 0}}),
    )
    store = upsert_march(
        store,
        stage=1,
        round_no=1,
        slot=1,
        march=parse_march({"counts": {"infantry": 0, "cavalry": 20, "archers": 0}}),
    )
    marches = get_stage_round(store, 1, 1)
    assert marches is not None
    assert marches[0]["counts"]["infantry"] == 10
    assert marches[1]["counts"]["cavalry"] == 20


def test_ratio_from_counts() -> None:
    r = ratio_from_counts({"infantry": 50, "cavalry": 30, "archers": 20})
    assert r is not None
    assert abs(r["infantry"] - 0.5) < 1e-9
    assert ratio_from_counts({"infantry": 0, "cavalry": 0, "archers": 0}) is None


def test_merge_saved_into_opponent() -> None:
    opponent = {
        "marches": [
            {
                "hero_names": ["AI", "AI", "AI"],
                "ratio": {"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3},
                "counts": {"infantry": 1, "cavalry": 1, "archers": 1},
                "levels": {"infantry": 6, "cavalry": 6, "archers": 6},
                "bonuses": {},
            },
            {
                "hero_names": ["AI", "AI", "AI"],
                "ratio": {"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3},
                "counts": {"infantry": 2, "cavalry": 2, "archers": 2},
                "levels": {"infantry": 6, "cavalry": 6, "archers": 6},
                "bonuses": {},
            },
        ],
        "bonuses": {},
    }
    saved = [
        parse_march(
            {
                "hero_names": ["Helga", "Jabel", "Diana"],
                "hero_level": 80,
                "gear_enhancement": 40,
                "levels": {"infantry": 8, "cavalry": 7, "archers": 6},
                "counts": {"infantry": 100, "cavalry": 0, "archers": 0},
                "bonuses": {"infantry": {"attack_pct": 50}},
            }
        ),
        parse_march({"counts": {"infantry": 0, "cavalry": 50, "archers": 50}}),
    ]
    merged = merge_saved_into_opponent(opponent, saved)
    assert merged is not None
    assert merged["saved"] is True
    assert merged["marches"][0]["hero_names"] == ["Helga", "Jabel", "Diana"]
    assert merged["marches"][0]["hero_level"] == 80
    assert merged["marches"][0]["gear_enhancement"] == 40
    assert merged["marches"][0]["levels"]["infantry"] == 8
    assert merged["marches"][0]["counts"]["infantry"] == 100
    assert abs(merged["marches"][0]["ratio"]["infantry"] - 1.0) < 1e-9
    assert merged["marches"][1]["counts"]["cavalry"] == 50


def test_parse_march_rejects_bad_level() -> None:
    with pytest.raises(ValueError, match="1–11"):
        parse_march({"levels": {"infantry": 12}})
