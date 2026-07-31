"""Sweep new-trap poses, pack seats, score layouts."""

from __future__ import annotations

from dataclasses import dataclass, field

from ks.placement.geometry import (
    Rect,
    city_rect,
    joiner_cycle_tiles,
    leader_cycle_tiles,
    new_trap_center,
    trap_rect,
)


@dataclass
class Blocker:
    id: str
    rect: Rect
    kind: str


@dataclass
class Seat:
    x: int
    y: int
    role: str = "joiner"  # leader_t2 | leader_t1 | both | joiner
    assigned_leader: tuple[int, int] | None = None
    t_l: float | None = None
    t_j: float | None = None


@dataclass
class LayoutResult:
    d: int
    direction: str
    lateral: int
    trap1: tuple[int, int]
    trap2: tuple[int, int]
    seats: list[Seat]
    score: float
    n_l2: int
    n_l1: int
    n_flex: int
    n_join_ok: int
    blockers: list[Blocker] = field(default_factory=list)


def _occupied(blockers: list[Blocker], traps: list[Rect]) -> list[Rect]:
    return [b.rect for b in blockers] + traps


def _fits(candidate: Rect, occupied: list[Rect]) -> bool:
    return all(not candidate.intersects(o) for o in occupied)


def pack_city_anchors(
    trap2: Rect,
    trap1: Rect,
    blockers: list[Blocker],
    city_size: int = 2,
    margin: int = 10,
) -> list[tuple[int, int]]:
    """Pack non-overlapping 2x2 cities in a bounding window around both traps."""
    xs = [trap2.x, trap2.x + trap2.w - 1, trap1.x, trap1.x + trap1.w - 1]
    ys = [trap2.y, trap2.y + trap2.h - 1, trap1.y, trap1.y + trap1.h - 1]
    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin

    occupied = _occupied(blockers, [trap2, trap1])
    anchors: list[tuple[int, int]] = []
    # Step by city_size so footprints tile without overlap (V3-style).
    for y in range(min_y, max_y + 1, city_size):
        for x in range(min_x, max_x + 1, city_size):
            c = city_rect(x, y, city_size)
            if _fits(c, occupied):
                anchors.append((x, y))
                occupied.append(c)
    return anchors


def _partition_leaders(
    anchors: list[tuple[int, int]],
    trap2: Rect,
    trap1: Rect,
    city_size: int,
    radius_leader: float,
    limit: int,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]], set[tuple[int, int]]]:
    """Assign near-trap seats to T2 / T1 / BOTH without starving one side."""
    both_cand: list[tuple[float, tuple[int, int]]] = []
    t2_cand: list[tuple[float, tuple[int, int]]] = []
    t1_cand: list[tuple[float, tuple[int, int]]] = []

    for ax, ay in anchors:
        city = city_rect(ax, ay, city_size)
        d2 = leader_cycle_tiles(city, trap2) / 2.0
        d1 = leader_cycle_tiles(city, trap1) / 2.0
        in2 = d2 <= radius_leader
        in1 = d1 <= radius_leader
        if in2 and in1:
            both_cand.append((min(d2, d1), (ax, ay)))
        elif in2:
            t2_cand.append((d2, (ax, ay)))
        elif in1:
            t1_cand.append((d1, (ax, ay)))

    both_cand.sort()
    t2_cand.sort()
    t1_cand.sort()

    both = {a for _, a in both_cand}
    # Fill each trap up to limit using exclusive candidates first, then BOTH overflow.
    l2 = {a for _, a in t2_cand[:limit]}
    l1 = {a for _, a in t1_cand[:limit]}
    for _, a in both_cand:
        if len(l2) < limit and a not in l1:
            # keep as BOTH visually; counts handled separately
            continue
    # Cap BOTH seats shown (middle band) but all both_cand remain BOTH role
    both = {a for _, a in both_cand[: max(limit, len(both_cand))]}
    # Exclusive leaders only
    l2 = {a for _, a in t2_cand[:limit]}
    l1 = {a for _, a in t1_cand[:limit]}
    both -= l2 | l1
    return l2, l1, both


def score_layout(
    trap2_xy: tuple[int, int],
    trap1_xy: tuple[int, int],
    blockers: list[Blocker],
    *,
    city_size: int = 2,
    trap_size: int = 3,
    radius_leader: float = 3.0,
    radius_joiner_cycle: float = 12.0,
    leaders_per_trap: int = 15,
    min_leaders: int = 10,
    weights: dict[str, float] | None = None,
) -> LayoutResult:
    w = weights or {}
    w1 = float(w.get("balanced_leaders", 5.0))
    w2 = float(w.get("total_leaders", 1.0))
    w3 = float(w.get("flex", 2.0))
    w4 = float(w.get("joiners", 1.0))
    penalty = float(w.get("under_min_penalty", 20.0))

    t2 = trap_rect(trap2_xy[0], trap2_xy[1], trap_size)
    t1 = trap_rect(trap1_xy[0], trap1_xy[1], trap_size)
    if t2.intersects(t1):
        return LayoutResult(
            d=-1,
            direction="?",
            lateral=0,
            trap1=trap1_xy,
            trap2=trap2_xy,
            seats=[],
            score=float("-inf"),
            n_l2=0,
            n_l1=0,
            n_flex=0,
            n_join_ok=0,
            blockers=blockers,
        )

    anchors = pack_city_anchors(t2, t1, blockers, city_size=city_size)
    l2, l1, both = _partition_leaders(
        anchors, t2, t1, city_size, radius_leader, leaders_per_trap
    )

    leader_rects = {
        **{a: (city_rect(a[0], a[1], city_size), t2) for a in l2},
        **{a: (city_rect(a[0], a[1], city_size), t1) for a in l1},
        **{a: (city_rect(a[0], a[1], city_size), t2) for a in both},
    }
    # BOTH seats count toward both traps' leader capacity
    n_l2 = len(l2) + len(both)
    n_l1 = len(l1) + len(both)

    seats: list[Seat] = []
    n_flex = 0
    n_join_ok = 0
    leader_list = [(a, city_rect(a[0], a[1], city_size), tr) for a, (_, tr) in leader_rects.items()]

    for ax, ay in anchors:
        city = city_rect(ax, ay, city_size)
        if (ax, ay) in both:
            seats.append(
                Seat(ax, ay, role="both", t_l=min(leader_cycle_tiles(city, t2), leader_cycle_tiles(city, t1)))
            )
            continue
        if (ax, ay) in l2:
            seats.append(Seat(ax, ay, role="leader_t2", t_l=leader_cycle_tiles(city, t2)))
            continue
        if (ax, ay) in l1:
            seats.append(Seat(ax, ay, role="leader_t1", t_l=leader_cycle_tiles(city, t1)))
            continue

        # Assign joiner to best leader by full t_J
        best = None
        best_tj = float("inf")
        second = float("inf")
        for la, lrect, trap in leader_list:
            tj = joiner_cycle_tiles(city, lrect, trap)
            if tj < best_tj:
                second = best_tj
                best_tj = tj
                best = la
            elif tj < second:
                second = tj
        flex = best is not None and second < float("inf") and (second - best_tj) <= 2.0
        if flex:
            n_flex += 1
        ok = best_tj <= radius_joiner_cycle
        if ok:
            n_join_ok += 1
        seats.append(
            Seat(
                ax,
                ay,
                role="joiner",
                assigned_leader=best,
                t_j=best_tj if best is not None else None,
            )
        )

    balanced = min(n_l2, n_l1, leaders_per_trap)
    score = (
        w1 * balanced
        + w2 * (n_l2 + n_l1)
        + w3 * n_flex
        + w4 * n_join_ok
    )
    if min(n_l2, n_l1) < min_leaders:
        score -= penalty * (min_leaders - min(n_l2, n_l1))

    return LayoutResult(
        d=-1,
        direction="?",
        lateral=0,
        trap1=trap1_xy,
        trap2=trap2_xy,
        seats=seats,
        score=score,
        n_l2=n_l2,
        n_l1=n_l1,
        n_flex=n_flex,
        n_join_ok=n_join_ok,
        blockers=blockers,
    )


def _apply_pose_bonuses(
    layout: LayoutResult,
    *,
    preferred_d: int,
    preferred_dirs: set[str],
    side_bonus: float,
    pref_d_bonus: float,
    pref_d_slope: float,
) -> None:
    if layout.direction in preferred_dirs:
        layout.score += side_bonus
    layout.score += pref_d_bonus - pref_d_slope * abs(layout.d - preferred_d)


def sweep(
    trap2_xy: tuple[int, int],
    blockers: list[Blocker],
    *,
    d_min: int = 5,
    d_max: int = 12,
    directions: list[str] | None = None,
    lateral_offsets: list[int] | None = None,
    trap_size: int = 3,
    preferred_d: int = 7,
    preferred_directions: list[str] | None = None,
    **score_kwargs,
) -> list[LayoutResult]:
    directions = directions or ["E", "W", "N", "S"]
    lateral_offsets = lateral_offsets if lateral_offsets is not None else [-1, 0, 1]
    preferred_dirs = set(preferred_directions or ["E", "W"])
    weights = dict(score_kwargs.get("weights") or {})
    results: list[LayoutResult] = []

    for d in range(d_min, d_max + 1):
        for direction in directions:
            for lateral in lateral_offsets:
                t1 = new_trap_center(trap2_xy[0], trap2_xy[1], d, direction, lateral)
                # New trap must not hit blockers
                t1_rect = trap_rect(t1[0], t1[1], trap_size)
                if any(t1_rect.intersects(b.rect) for b in blockers):
                    continue
                layout = score_layout(trap2_xy, t1, blockers, trap_size=trap_size, **score_kwargs)
                if layout.score == float("-inf"):
                    continue
                layout.d = d
                layout.direction = direction
                layout.lateral = lateral
                _apply_pose_bonuses(
                    layout,
                    preferred_d=preferred_d,
                    preferred_dirs=preferred_dirs,
                    side_bonus=float(weights.get("side_by_side_bonus", 0.0)),
                    pref_d_bonus=float(weights.get("preferred_d_bonus", 0.0)),
                    pref_d_slope=float(weights.get("preferred_d_slope", 0.0)),
                )
                results.append(layout)

    results.sort(key=lambda r: r.score, reverse=True)
    return results
