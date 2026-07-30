"""Tests for cartograph jump planner."""

import pytest

from ks.cartograph.sweep import plan_jumps


def test_plan_covers_bbox_and_center() -> None:
    plan = plan_jumps(698, 816, radius=30, step=10)
    assert plan.center == (698, 816)
    xs = {j[0] for j in plan.jumps}
    ys = {j[1] for j in plan.jumps}
    assert 698 in xs and 816 in ys
    assert min(xs) == 668 and max(xs) == 728
    assert min(ys) == 786 and max(ys) == 846
    assert (0, 0) in plan.swipe_offsets


def test_radius_bounds() -> None:
    with pytest.raises(ValueError):
        plan_jumps(0, 0, radius=10)
    with pytest.raises(ValueError):
        plan_jumps(0, 0, radius=60)
