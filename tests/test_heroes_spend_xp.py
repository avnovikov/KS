"""Tests for fodder XP allocation (knapsack-style greedy ΔU/XP)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.spend_xp import (
    SpendStep,
    _merge_consecutive_runs,
    allocate_fodder_xp,
    apply_levels,
    build_event_utility,
)
from ks.heroes.optimize.xp_ladder import FodderBag, load_fodder_xp_values, load_xp_ladder


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


def test_allocate_reports_real_progress_by_default(capsys: pytest.CaptureFixture) -> None:
    """The search re-solves the target event once per affordable candidate
    piece, so a real inventory can take a while — this must never be a
    silent wait: real, running progress on stdout, not just a status string
    the caller has to trust. Sorted (best ΔU/XP first) and capped, not a
    flat unordered dump of every piece in the bag."""
    gear = [
        _piece("a", level=0, troop="infantry", slot="helmet"),
        _piece("b", level=0, troop="cavalry", slot="helmet"),
    ]

    def utility(g):
        levels = {p.piece_id: int(p.enhancement_level or 0) for p in g}
        u = 100.0 * levels.get("a", 0) + 1.0 * levels.get("b", 0)
        return u, {"levels": levels}

    bag = FodderBag(grey=5)
    allocate_fodder_xp(gear, bag, utility, event="test", max_steps=2)
    out = capsys.readouterr().out
    assert "[gear-xp] searching event=test" in out
    assert "2 gear piece(s)" in out
    assert "step 1/2" in out
    assert "-> chose Piece a" in out
    assert "done: " in out
    # Ranked, not a flat dump: the better candidate is listed before the
    # worse one under the same step.
    step1 = out.split("step 1/2", 1)[1].split("step 2/2", 1)[0]
    assert step1.index("Piece a") < step1.index("Piece b")


def test_allocate_verbose_false_is_silent(capsys: pytest.CaptureFixture) -> None:
    gear = [_piece("a", level=0, troop="infantry", slot="helmet")]

    def utility(g):
        levels = {p.piece_id: int(p.enhancement_level or 0) for p in g}
        return 100.0 * levels.get("a", 0), {}

    bag = FodderBag(grey=5)
    allocate_fodder_xp(gear, bag, utility, event="test", max_steps=2, verbose=False)
    assert capsys.readouterr().out == ""


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


def test_merge_consecutive_runs_recombines_fodder_for_less_waste() -> None:
    """Two levels on the same piece, each independently forced to round up
    to a whole 100-XP part because nothing smaller was available *at that
    step*, can waste more overall (200 XP of fodder for 120 XP of real
    cost) than covering their combined real cost in one plan. By the time
    the run ends some grey has freed up elsewhere in the bag, so the merge
    finds the exact-cost 1×part_100 + 2×grey cover instead."""
    steps = [
        SpendStep(
            piece_id="a", name="Crusader's Breastplate", from_level=9, to_level=10,
            xp_spent=55, fodder_spent={"part_100": 1},
        ),
        SpendStep(
            piece_id="a", name="Crusader's Breastplate", from_level=10, to_level=11,
            xp_spent=65, fodder_spent={"part_100": 1},
        ),
    ]
    final_bag = FodderBag(grey=5, part_100=3)
    values = load_fodder_xp_values()
    merged, new_bag = _merge_consecutive_runs(steps, final_bag, values)

    assert len(merged) == 1
    step = merged[0]
    assert step.piece_id == "a"
    assert step.name == "Crusader's Breastplate"
    assert step.from_level == 9
    assert step.to_level == 11
    assert step.xp_spent == 120
    assert step.fodder_spent == {"part_100": 1, "grey": 2}
    # Refunding the run's naive 2×part_100 and re-covering 120 XP exactly
    # frees a part_100 and spends 2 of the 5 grey that had freed up elsewhere.
    assert new_bag.part_100 == 4
    assert new_bag.grey == 3


def test_merge_consecutive_runs_leaves_non_adjacent_or_single_steps_alone() -> None:
    steps = [
        SpendStep(piece_id="a", name="A", from_level=0, to_level=1, xp_spent=10, fodder_spent={"grey": 1}),
        SpendStep(piece_id="b", name="B", from_level=0, to_level=1, xp_spent=10, fodder_spent={"grey": 1}),
        SpendStep(piece_id="a", name="A", from_level=1, to_level=2, xp_spent=15, fodder_spent={"grey": 2}),
    ]
    bag = FodderBag(grey=10)
    values = load_fodder_xp_values()
    merged, new_bag = _merge_consecutive_runs(steps, bag, values)
    # "a" appears twice but not consecutively (separated by "b"), so nothing
    # merges and the bag is untouched.
    assert merged == steps
    assert new_bag == bag


def test_allocate_fodder_xp_merges_consecutive_levels_on_the_same_piece() -> None:
    """End-to-end: the same wiring the unit test above exercises directly,
    reached through the real search — a piece kept as the best pick for two
    consecutive levels reports as one merged SpendStep, not two."""
    gear = [_piece("a", level=9, rarity="epic")]  # epic cap 80

    def utility(g):
        lv = int(g[0].enhancement_level or 0)
        return float(lv), {"level": lv}

    ladder = load_xp_ladder()
    bag = FodderBag(grey=5, part_100=3)
    result = allocate_fodder_xp(
        gear, bag, utility, event="test", max_steps=2, ladder=ladder
    )
    assert len(result.steps) == 1
    assert result.steps[0].piece_id == "a"
    assert result.steps[0].from_level == 9
    assert result.steps[0].to_level == 11


def test_allocate_stops_when_no_positive_delta() -> None:
    gear = [_piece("a", level=1)]

    def utility(g):
        return 1.0, {}  # constant

    bag = FodderBag(grey=10)
    result = allocate_fodder_xp(gear, bag, utility, event="test", max_steps=5)
    assert result.steps == ()
    assert result.leftover.grey == 10


def test_allocate_prefers_delta_u_per_xp_over_raw_delta() -> None:
    """Expensive +1 with higher raw ΔU must lose to cheap +1 with better ΔU/XP.

    Mirrors the Arena gift-bag failure mode: Praetorian +1 (ΔU≈0.065, XP=310)
    beat Stonewall +1 (ΔU≈0.043, XP=45) under raw-ΔU greedy.
    """
    ladder = load_xp_ladder()
    # blue@7 → next costs 45; epic@41 → next costs 310
    gear = [
        _piece("cheap", level=7, rarity="blue", troop="infantry", slot="chest"),
        _piece("pricey", level=41, rarity="epic", troop="infantry", slot="gloves"),
    ]

    def utility(g):
        levels = {p.piece_id: int(p.enhancement_level or 0) for p in g}
        # +1 cheap → ΔU=50; +1 pricey → ΔU=100 (wins raw ΔU, loses ΔU/XP)
        u = 50.0 * (levels.get("cheap", 7) - 7) + 100.0 * (levels.get("pricey", 41) - 41)
        return u, {"levels": levels}

    bag = FodderBag(part_100=4)  # 400 XP — enough for either first step
    result = allocate_fodder_xp(
        gear, bag, utility, event="test", max_steps=1, ladder=ladder
    )
    assert result.steps, "expected one upgrade step"
    assert result.steps[0].piece_id == "cheap"
    assert result.steps[0].from_level == 7
    assert result.steps[0].to_level == 8


_ROOT = Path(__file__).resolve().parents[1]

# Names must exist in config/hero_catalog.yaml so the real catalog resolves;
# optimize_arena drops heroes the catalog does not know and needs five.
_ROSTER = [
    ("Helga", "infantry", "legendary", 3, 500_000),
    ("Howard", "infantry", "epic", 3, 390_000),
    ("Jabel", "cavalry", "legendary", 4, 650_000),
    ("Chenko", "cavalry", "epic", 3, 400_000),
    ("Saul", "archer", "legendary", 2, 250_000),
    ("Diana", "archer", "epic", 3, 450_000),
    ("Gordon", "cavalry", "epic", 2, 230_000),
]


def _heroes() -> list[HeroRecord]:
    return [
        HeroRecord(
            name=name,
            troop_type=troop,
            rarity=rarity,
            stars=stars,
            pellets=0,
            power=power,
            escorts=5,
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for name, troop, rarity, stars, power in _ROSTER
    ]


def _gear() -> list[GearRecord]:
    return [
        _piece(f"{troop}-{slot}", level=20, troop=troop, slot=slot)
        for troop in ("infantry", "cavalry", "archers")
        for slot in ("helmet", "chest", "gloves", "boots")
    ]


def test_arena_utility_summary_carries_contributions() -> None:
    utility = build_event_utility("arena_attack", _heroes(), config_root=_ROOT)
    _util, summary = utility(_gear())
    assert summary["stat_family"] == "conquest"
    totals = summary["formation_totals"]
    assert set(totals["power"]) == {"hero", "skills", "gear", "total"}
    assert totals["power"]["total"] == pytest.approx(
        totals["power"]["hero"] + totals["power"]["skills"] + totals["power"]["gear"]
    )


def test_event_utility_summary_carries_contributions() -> None:
    utility = build_event_utility("swordland", _heroes(), config_root=_ROOT)
    _util, summary = utility(_gear())
    assert summary["stat_family"] == "expedition"
    assert summary["formation_totals"] is not None


def test_levelling_gear_raises_gear_share_of_totals() -> None:
    utility = build_event_utility("arena_attack", _heroes(), config_root=_ROOT)
    base_gear = _gear()
    _u0, s0 = utility(base_gear)
    bumped = apply_levels(
        base_gear, {p.piece_id: (p.enhancement_level or 0) + 20 for p in base_gear}
    )
    _u1, s1 = utility(bumped)
    assert (
        s1["formation_totals"]["power"]["gear"]
        > s0["formation_totals"]["power"]["gear"]
    )
