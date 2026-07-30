"""Plan coarse coord jumps (+ optional swipe offsets) for a cartograph radius."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JumpPlan:
    center: tuple[int, int]
    radius: int
    step: int
    jumps: tuple[tuple[int, int], ...]
    swipe_offsets: tuple[tuple[int, int], ...]  # tile deltas after each jump


def plan_jumps(
    cx: int,
    cy: int,
    radius: int,
    step: int = 10,
    *,
    swipe_offsets: tuple[tuple[int, int], ...] | None = None,
) -> JumpPlan:
    """Build a coarse grid of world coords covering [cx±R, cy±R].

    ``step`` is the coord-jump spacing in tiles (≈8–10). Optional
    ``swipe_offsets`` are small tile deltas applied via swipe after each jump
    to increase overlap (default: origin only + four half-step cardinals).
    """
    if not (20 <= radius <= 50):
        raise ValueError(f"radius must be in 20..50; got {radius}")
    if step < 1:
        raise ValueError(f"step must be >= 1; got {step}")

    xs = list(range(cx - radius, cx + radius + 1, step))
    ys = list(range(cy - radius, cy + radius + 1, step))
    # Ensure max edge included when radius not divisible by step.
    if xs[-1] != cx + radius:
        xs.append(cx + radius)
    if ys[-1] != cy + radius:
        ys.append(cy + radius)
    if cx not in xs:
        xs.append(cx)
        xs.sort()
    if cy not in ys:
        ys.append(cy)
        ys.sort()

    jumps = tuple((x, y) for y in ys for x in xs)

    if swipe_offsets is None:
        half = max(1, step // 2)
        swipe_offsets = (
            (0, 0),
            (half, 0),
            (-half, 0),
            (0, half),
            (0, -half),
        )

    return JumpPlan(
        center=(cx, cy),
        radius=radius,
        step=step,
        jumps=jumps,
        swipe_offsets=swipe_offsets,
    )
