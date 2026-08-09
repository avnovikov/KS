"""Mystic Trial room config loader tests."""

from __future__ import annotations

from pathlib import Path

from ks.heroes.optimize.mystic_trial.rooms import load_room

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "mystic_trial"


def test_load_molten_fort_seed_and_focus() -> None:
    room = load_room(CFG / "molten_fort.yaml")
    assert room.id == "molten_fort"
    assert room.focus == "governor"
    assert abs(room.seed_ratio["infantry"] - 0.60) < 1e-9
    assert abs(room.seed_ratio["cavalry"] - 0.15) < 1e-9
    assert abs(room.seed_ratio["archers"] - 0.25) < 1e-9
    assert room.active_marches == 1


def test_load_coliseum_heroes_gear_focus() -> None:
    room = load_room(CFG / "coliseum.yaml")
    assert room.focus == "heroes_gear"
    assert abs(room.seed_ratio["infantry"] - 0.50) < 1e-9
    assert abs(room.seed_ratio["cavalry"] - 0.10) < 1e-9
    assert abs(room.seed_ratio["archers"] - 0.40) < 1e-9


def test_load_radiant_event_march_capacity() -> None:
    room = load_room(CFG / "radiant_spire.yaml")
    assert room.id == "radiant_spire"
    assert room.event_march_capacity == 150_000
    assert room.active_marches == 2
