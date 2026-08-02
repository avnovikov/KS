"""Vision count of hero star progress: full yellow stars + pellets on the next star.

UI: 5 star slots; each star is 6 triangular pellets. Completed stars are fully
yellow; the in-progress star has 0–5 yellow pellets; remaining slots are empty.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ks.heroes.config import OcrBox

STAR_SLOTS = 5
PELLETS_PER_STAR = 6


@dataclass(frozen=True)
class StarProgress:
    """``stars`` = completed slots; ``pellets`` = yellow pellets on the next slot."""

    stars: int
    pellets: int
    per_slot: tuple[int, ...]

    @property
    def total_pellets(self) -> int:
        return self.stars * PELLETS_PER_STAR + self.pellets


def _gold_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (12, 60, 140), (48, 255, 255))


def count_slot_pellets(gold_slot: np.ndarray, *, full_ref: float) -> int:
    """Estimate 0–6 pellets in one star slot from yellow pixel mass."""
    if gold_slot.size == 0:
        return 0
    yp = float(gold_slot.sum() // 255)
    if full_ref <= 1 or yp < full_ref * 0.08:
        return 0
    pellets = int(round(PELLETS_PER_STAR * yp / full_ref))
    return max(0, min(PELLETS_PER_STAR, pellets))


def _stars_box_to_xywh(
    image: np.ndarray, box: OcrBox | tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    if isinstance(box, OcrBox):
        x, y, w, h = box.x, box.y, box.w, box.h
    else:
        x, y, w, h = box
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid stars box w={w} h={h}")
    ih, iw = image.shape[:2]
    x2, y2 = min(iw, x + w), min(ih, y + h)
    if x >= iw or y >= ih or x2 <= x or y2 <= y:
        raise ValueError(f"stars box out of bounds: {(x, y, w, h)} image={iw}x{ih}")
    return x, y, x2, y2


def _slice_star_slots(gold: np.ndarray) -> list[np.ndarray]:
    """Split the gold-mask strip into ``STAR_SLOTS`` equal-width columns."""
    sw = max(1, gold.shape[1] // STAR_SLOTS)
    slices: list[np.ndarray] = []
    for i in range(STAR_SLOTS):
        x0 = i * sw
        x1 = gold.shape[1] if i == STAR_SLOTS - 1 else (i + 1) * sw
        slices.append(gold[:, x0:x1])
    return slices


def _full_star_reference(slices: list[np.ndarray]) -> float:
    """Yellow-pixel mass that counts as one "full" star slot.

    Uses the median of slots that are at least 55% as bright as the
    brightest slot, to filter out empty/partial slots when estimating the
    reference brightness for a complete star.
    """
    yps = [float(slot.sum() // 255) for slot in slices]
    positive = [yp for yp in yps if yp >= max(yps) * 0.55] if max(yps) > 0 else []
    full_ref = float(np.median(positive)) if positive else (max(yps) if yps else 1.0)
    return full_ref if full_ref >= 1 else 1.0


def _stars_and_pellets(per_slot: tuple[int, ...]) -> tuple[int, int]:
    """Count completed stars, then the pellet count of the first incomplete slot."""
    stars = 0
    pellets = 0
    for p in per_slot:
        if p >= PELLETS_PER_STAR:
            stars += 1
        else:
            pellets = p
            break
    return stars, pellets


def count_stars_pellets(
    image: np.ndarray,
    box: OcrBox | tuple[int, int, int, int],
) -> StarProgress:
    """Count full stars and in-progress pellets from a detail-screen crop box."""
    if image.ndim != 3:
        raise ValueError("image must be BGR")
    x, y, x2, y2 = _stars_box_to_xywh(image, box)

    strip = image[y:y2, x:x2]
    gold = _gold_mask(strip)
    slices = _slice_star_slots(gold)
    full_ref = _full_star_reference(slices)

    per_slot = tuple(count_slot_pellets(slot, full_ref=full_ref) for slot in slices)
    stars, pellets = _stars_and_pellets(per_slot)

    assert 0 <= stars <= STAR_SLOTS, f"stars out of range: {stars}"
    assert 0 <= pellets <= PELLETS_PER_STAR, f"pellets out of range: {pellets}"
    return StarProgress(stars=stars, pellets=pellets, per_slot=per_slot)
