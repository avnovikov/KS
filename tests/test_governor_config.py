"""Tests for governor gear config, ladder, and troop bonuses."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.governor_bonuses import governor_troop_bonuses
from ks.heroes.governor_config import (
    ladder_index,
    ladder_step,
    load_governor_gear_config,
    next_ladder_step,
    slot_troop,
)
from ks.heroes.governor_models import GovernorPiece

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "governor_gear.yaml"


def test_slots_map_to_troops() -> None:
    cfg = load_governor_gear_config(CFG)
    assert slot_troop(cfg, "hood") == "cavalry"
    assert slot_troop(cfg, "cloak") == "infantry"
    assert slot_troop(cfg, "ring") == "archers"
    assert set(cfg.slots) == {
        "hood",
        "necklace",
        "cloak",
        "breeches",
        "ring",
        "staff",
    }


def test_ladder_step_and_upgrade() -> None:
    cfg = load_governor_gear_config(CFG)
    step0 = ladder_step(cfg, "green", 0)
    assert step0 is not None
    assert step0.attack_pct == pytest.approx(9.35)
    nxt = next_ladder_step(cfg, "green", 0)
    assert nxt is not None
    assert nxt.tier == "green"
    assert nxt.stars == 1
    assert ladder_index(cfg, "red", 0) == len(cfg.ladder) - 1
    assert next_ladder_step(cfg, "red", 0) is None


def test_three_piece_set_gives_defense_bonus_only() -> None:
    cfg = load_governor_gear_config(CFG)
    pieces = [
        GovernorPiece(slot_id="hood", tier="blue", stars=0),
        GovernorPiece(slot_id="necklace", tier="blue", stars=1),
        GovernorPiece(slot_id="cloak", tier="blue", stars=0),
        GovernorPiece(slot_id="breeches", tier="green", stars=0),
        GovernorPiece(slot_id="ring", tier="green", stars=0),
        GovernorPiece(slot_id="staff", tier="green", stars=0),
    ]
    # Enrich from ladder for pcts
    for i, p in enumerate(pieces):
        step = ladder_step(cfg, p.tier, p.stars)
        assert step is not None
        pieces[i] = p.with_ladder(step)
    bonuses = governor_troop_bonuses(pieces, cfg)
    assert bonuses.set_defense_pct == pytest.approx(3.0)  # blue 3pc
    assert bonuses.set_attack_pct == pytest.approx(0.0)  # not 6 matching
    assert bonuses.attack_pct["cavalry"] > bonuses.attack_pct["archers"]


def test_six_piece_same_tier_gives_attack_and_defense_set() -> None:
    cfg = load_governor_gear_config(CFG)
    pieces = []
    for slot in cfg.slots:
        step = ladder_step(cfg, "purple", 0)
        assert step is not None
        pieces.append(
            GovernorPiece(slot_id=slot, tier="purple", stars=0).with_ladder(step)
        )
    bonuses = governor_troop_bonuses(pieces, cfg)
    assert bonuses.set_defense_pct == pytest.approx(5.0)
    assert bonuses.set_attack_pct == pytest.approx(5.0)
    # Each troop gets 2 pieces' atk + set attack
    assert bonuses.attack_pct["infantry"] == pytest.approx(34.0 + 34.0 + 5.0)
