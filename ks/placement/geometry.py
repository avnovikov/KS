"""Bear-trap hive geometry and march distances (tile Chebyshev)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def intersects(self, other: Rect) -> bool:
        return not (
            self.x + self.w <= other.x
            or other.x + other.w <= self.x
            or self.y + self.h <= other.y
            or other.y + other.h <= self.y
        )

    def contains_point(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + (self.w - 1) / 2.0, self.y + (self.h - 1) / 2.0)


def chebyshev(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def trap_rect(cx: int, cy: int, trap_size: int = 3) -> Rect:
    assert trap_size >= 1 and trap_size % 2 == 1, f"trap_size must be odd; got {trap_size}"
    half = trap_size // 2
    return Rect(cx - half, cy - half, trap_size, trap_size)


def city_rect(anchor_x: int, anchor_y: int, city_size: int = 2) -> Rect:
    assert city_size >= 1, f"city_size must be positive; got {city_size}"
    return Rect(anchor_x, anchor_y, city_size, city_size)


def leader_cycle_tiles(leader: Rect, trap: Rect) -> float:
    """t_L = 2 * march(leader, trap)."""
    return 2.0 * chebyshev(leader.center, trap.center)


def joiner_cycle_tiles(joiner: Rect, leader: Rect, trap: Rect) -> float:
    """t_J = joiner→leader + leader→trap + trap→joiner."""
    return (
        chebyshev(joiner.center, leader.center)
        + chebyshev(leader.center, trap.center)
        + chebyshev(trap.center, joiner.center)
    )


DIRECTION_DELTA = {
    "E": (1, 0),
    "W": (-1, 0),
    "N": (0, -1),
    "S": (0, 1),
}


def new_trap_center(
    trap2_x: int,
    trap2_y: int,
    distance: int,
    direction: str,
    lateral: int,
) -> tuple[int, int]:
    assert distance >= 1, f"distance must be >= 1; got {distance}"
    assert direction in DIRECTION_DELTA, f"unknown direction {direction!r}"
    dx, dy = DIRECTION_DELTA[direction]
    # Perpendicular unit for lateral offset
    lx, ly = (-dy, dx)
    return (
        trap2_x + dx * distance + lx * lateral,
        trap2_y + dy * distance + ly * lateral,
    )
