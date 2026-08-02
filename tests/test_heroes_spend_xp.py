"""Tests for fodder XP allocation (knapsack-style greedy ΔU)."""

from __future__ import annotations

from ks.heroes.gear_models import GearRecord
from ks.heroes.optimize.spend_xp import allocate_fodder_xp, apply_levels
from ks.heroes.optimize.xp_ladder import FodderBag, load_xp_ladder


def _piece(
    pid: str,
    *,
    level: int = 0,
    rarity: str = "mythic",
    troop: str = "infantry",
    slot: str = "helmet",
    power: int = 10_000,
) -> GearRecord:
    return GearRecord(
        piece_id=pid,
        name=f"Piece {pid}",
        troop_type=troop,
        slot=slot,
        rarity=rarity,
        enhancement_level=level,
        power=power,
    )


def test_allocate_prefers_piece_that_raises_utility() -> None:
    gear = [
        _piece("a", level=0, troop="infantry", slot="helmet"),
        _piece("b", level=0, troop="cavalry", slot="helmet"),
    ]
    # Utility = 100 * level(a) + 1 * level(b)
    def utility(g):
        levels = {p.piece_id: int(p.enhancement_level or 0) for p in g}
        u = 100.0 * levels.get("a", 0) + 1.0 * levels.get("b", 0)
        return u, {"levels": levels}

    bag = FodderBag(grey=5)  # 50 XP — enough for several early levels
    result = allocate_fodder_xp(gear, bag, utility, event="test", max_steps=5)
    assert result.best_utility > result.baseline_utility
    assert result.steps
    assert result.steps[0].piece_id == "a"
    assert all(s.piece_id == "a" for s in result.steps)


def test_allocate_respects_cap() -> None:
    ladder = load_xp_ladder()
    # Epic cap 80 — start at 79, one grey may not cover next cost; give part_100
    gear = [_piece("a", level=79, rarity="epic")]
    calls = {"n": 0}

    def utility(g):
        calls["n"] += 1
        lv = int(g[0].enhancement_level or 0)
        return float(lv), {"level": lv}

    bag = FodderBag(part_100=20)
    result = allocate_fodder_xp(
        gear, bag, utility, event="test", max_steps=5, ladder=ladder
    )
    assert all(s.to_level <= 80 for s in result.steps)
    final = apply_levels(gear, {gear[0].piece_id: result.steps[-1].to_level}) if result.steps else gear
    assert int(final[0].enhancement_level or 0) <= 80


def test_allocate_stops_when_no_positive_delta() -> None:
    gear = [_piece("a", level=1)]

    def utility(g):
        return 1.0, {}  # constant

    bag = FodderBag(grey=10)
    result = allocate_fodder_xp(gear, bag, utility, event="test", max_steps=5)
    assert result.steps == ()
    assert result.leftover.grey == 10
