"""Unit tests for bear-trap placement geometry and sweep."""

from __future__ import annotations

from ks.placement.geometry import (
    joiner_cycle_tiles,
    leader_cycle_tiles,
    city_rect,
    new_trap_center,
    trap_rect,
)
from ks.placement.sweep import Blocker, Rect, score_layout, sweep


def test_new_trap_east_d7():
    assert new_trap_center(701, 816, 7, "E", 0) == (708, 816)


def test_leader_and_joiner_cycle_math():
    trap = trap_rect(701, 816, 3)
    leader = city_rect(698, 814, 2)
    joiner = city_rect(694, 812, 2)
    t_l = leader_cycle_tiles(leader, trap)
    t_j = joiner_cycle_tiles(joiner, leader, trap)
    assert t_l == 2 * max(abs(leader.center[0] - trap.center[0]), abs(leader.center[1] - trap.center[1]))
    assert t_j > t_l / 2


def test_sweep_prefers_feasible_non_overlapping():
    blockers: list[Blocker] = []
    ranked = sweep((701, 816), blockers, d_min=6, d_max=8, directions=["E"], lateral_offsets=[0])
    assert ranked
    assert ranked[0].trap1[0] > 701
    assert ranked[0].n_l2 >= 1
    assert ranked[0].n_l1 >= 1


def test_blocker_rejects_trap_on_building():
    blockers = [Blocker("wall", Rect(707, 815, 3, 3), "building")]
    ranked = sweep((701, 816), blockers, d_min=7, d_max=7, directions=["E"], lateral_offsets=[0])
    # Exact center (708,816) with 3x3 trap may intersect — either empty or shifted away
    for r in ranked:
        t1 = trap_rect(r.trap1[0], r.trap1[1], 3)
        assert not t1.intersects(blockers[0].rect)


def test_closer_d_can_reduce_unique_leaders_on_empty_map():
    empty: list[Blocker] = []
    close = score_layout((701, 816), (706, 816), empty, radius_leader=4.0, leaders_per_trap=15)
    far = score_layout((701, 816), (712, 816), empty, radius_leader=4.0, leaders_per_trap=15)
    # Farther traps generally yield more unique leader seats before flex collapses
    assert far.n_l2 + far.n_l1 >= close.n_l2 + close.n_l1 - 2
