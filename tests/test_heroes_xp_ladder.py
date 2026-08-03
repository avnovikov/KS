"""Tests for enhancement XP ladder and typed fodder bag."""

from __future__ import annotations

from ks.heroes.optimize.xp_ladder import (
    FodderBag,
    cap_for_rarity,
    load_fodder_xp_values,
    load_xp_ladder,
    xp_cost_between,
)


def test_fodder_xp_values_match_config() -> None:
    vals = load_fodder_xp_values()
    assert vals["grey"] == 10
    assert vals["green"] == 30
    assert vals["blue"] == 60
    assert vals["purple"] == 150
    assert vals["part_100"] == 100


def test_cap_for_rarity() -> None:
    assert cap_for_rarity("grey") == 20
    assert cap_for_rarity("green") == 40
    assert cap_for_rarity("blue") == 60
    assert cap_for_rarity("epic") == 80
    assert cap_for_rarity("mythic") == 100
    assert cap_for_rarity("red") == 200


def test_xp_cost_between_levels() -> None:
    ladder = load_xp_ladder()
    # cumulative 0→5 = 100 from yaml sample
    assert xp_cost_between(ladder, 0, 5) == 100
    assert xp_cost_between(ladder, 5, 5) == 0
    assert xp_cost_between(ladder, 4, 5) == 30  # level 5 xp_cost


def test_fodder_bag_covers_cost_with_green_and_grey() -> None:
    bag = FodderBag(grey=2, green=1, blue=0, purple=0, part_100=0)
    plan = bag.plan_cover(40)
    assert plan is not None
    # 1 green (30) + 1 grey (10)
    assert plan == {"green": 1, "grey": 1}
    bag2 = bag.consume(plan)
    assert bag2.grey == 1
    assert bag2.green == 0


def test_fodder_bag_prefers_small_denoms_over_wasting_part_100() -> None:
    """Do not spend a 100-pt plate on a 45 XP step when greys/greens can cover."""
    bag = FodderBag(grey=5, green=5, blue=0, purple=0, part_100=22)
    plan = bag.plan_cover(45)
    assert plan is not None
    assert plan.get("part_100", 0) == 0
    vals = load_fodder_xp_values()
    spent = sum(plan[k] * vals[k] for k in plan)
    assert spent >= 45
    assert spent - 45 <= 5  # e.g. 5 grey = 50, waste 5 — not a full plate


def test_fodder_bag_uses_exact_part_100_when_waste_tied() -> None:
    """When a plate covers exactly, prefer it over many greys/greens."""
    bag = FodderBag(grey=5, green=5, blue=0, purple=0, part_100=22)
    plan = bag.plan_cover(100)
    assert plan == {"part_100": 1}


def test_fodder_bag_cannot_cover() -> None:
    bag = FodderBag(grey=1, green=0, blue=0, purple=0, part_100=0)
    assert bag.plan_cover(30) is None
