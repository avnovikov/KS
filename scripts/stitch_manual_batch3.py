#!/usr/bin/env python3
"""Manual panorama stitch — align shots on Hunting Trap blue beam."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BATCH3 = ROOT / "assets" / "reference" / "bear-trap" / "blockers-shots" / "batch3"
OUT = ROOT / "assets" / "reference" / "bear-trap" / "panorama-manual-batch3.png"


@dataclass
class Placed:
    name: str
    image: np.ndarray
    ox: float
    oy: float
    beam: tuple[int, int] | None = None


def crop_map(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    return img[int(h * 0.14) : int(h * 0.72), int(w * 0.06) : int(w * 0.94)]


def mask_pip(img: np.ndarray) -> np.ndarray:
    """Hide bottom-left PiP mini-map so it does not confuse alignment."""
    out = img.copy()
    h, w = out.shape[:2]
    cv2.rectangle(out, (0, int(h * 0.55)), (int(w * 0.32), h), (18, 28, 18), -1)
    return out


def _find_in_roi(
    roi: np.ndarray,
    y_offset: int,
    *,
    mode: str,
    cx_target: float,
    x_min: float = 0.0,
    x_max: float = 1.0,
) -> tuple[tuple[int, int], float] | None:
    h, w = roi.shape[:2]
    x0_band = int(w * x_min)
    x1_band = int(w * x_max)
    band = roi[:, x0_band:x1_band]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    if mode == "flames":
        mask = cv2.inRange(hsv, (5, 90, 120), (30, 255, 255))
        mask |= cv2.inRange(hsv, (0, 90, 120), (8, 255, 255))
        min_area = 120
    else:
        mask = cv2.inRange(hsv, (95, 80, 140), (135, 255, 255))
        min_area = 80
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    best_score = 0.0
    bw = band.shape[1]
    for i in range(1, n):
        _x, _y, _bw, bh, area = stats[i]
        if area < min_area:
            continue
        if mode == "blue" and bh < 18:
            continue
        cx, cy = centroids[i]
        cx_full = cx + x0_band
        dist = abs(cx - cx_target - x0_band) / max(bw, 1)
        score = area * (1.0 - 1.2 * dist)
        if score > best_score:
            best_score = score
            best = (int(round(cx_full)), int(round(cy + y_offset)), score)
    return best


def find_anchor(img: np.ndarray) -> tuple[int, int]:
    """Trap anchor: orange fire or blue beam in the bottom trap band."""
    h, w = img.shape[:2]
    x0, x1 = int(w * 0.30), int(w * 0.70)
    y0, y1 = int(h * 0.68), int(h * 0.92)
    sub = img[y0:y1, x0:x1]
    cx_target = sub.shape[1] / 2

    best_pt: tuple[int, int] | None = None
    best_score = 0.0
    for mode in ("flames", "blue"):
        hit = _find_in_roi(sub, y0, mode=mode, cx_target=cx_target)
        if hit and hit[2] > best_score:
            best_score = hit[2]
            best_pt = (hit[0] + x0, hit[1])
    if best_pt is None:
        raise AssertionError("no trap anchor found")
    return best_pt


def align_by_trap_patch(img7: np.ndarray, img6: np.ndarray, anchor7: tuple[int, int]) -> tuple[float, float]:
    """Place img6 so the trap neighbourhood matches img7."""
    h, w = img7.shape[:2]
    r = 160
    ax, ay = anchor7
    x0, y0 = max(0, ax - r), max(0, ay - r)
    x1, y1 = min(w, ax + r), min(h, ay + r)
    patch = img7[y0:y1, x0:x1]
    ph, pw = patch.shape[:2]

    search = img6[int(h * 0.55) :, :]
    y_bias = int(h * 0.55)
    res = cv2.matchTemplate(
        cv2.cvtColor(search, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY),
        cv2.TM_CCOEFF_NORMED,
    )
    _, score, _, max_loc = cv2.minMaxLoc(res)
    ox = x0 - max_loc[0]
    oy = y0 - (max_loc[1] + y_bias)
    print(f"  trap patch match score={score:.3f} -> ({ox:.1f},{oy:.1f})")
    if score > 0.25:
        return float(ox), float(oy)
    return float(ax - find_anchor(img6)[0]), float(ay - find_anchor(img6)[1])


def refine_beam_offset(
    anchor: np.ndarray, other: np.ndarray, guess: tuple[float, float], radius: int = 220
) -> tuple[float, float]:
    """Refine offset by matching a square patch around the anchor point."""
    ax, ay = guess
    h, w = anchor.shape[:2]
    # Patch centre on anchor canvas = guess point on other aligns to (0,0) anchor anchor-point
    # We want: other placed at (ox,oy) so other[anchor_pt] aligns with anchor[anchor_pt at origin]
    # Anchor anchor point in anchor img is beam7; we use template from anchor at beam7
    beam_x = int(round(-ax)) if ax != 0 else w // 2
    beam_y = int(round(-ay)) if ay != 0 else h // 2
    # Use lower-centre trap patch from anchor
    beam_x, beam_y = w // 2, int(h * 0.72)
    r = radius
    x0, y0 = max(0, beam_x - r), max(0, beam_y - r)
    x1, y1 = min(w, beam_x + r), min(h, beam_y + r)
    patch = anchor[y0:y1, x0:x1]
    if patch.size == 0:
        return guess

    res = cv2.matchTemplate(
        cv2.cvtColor(other, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY),
        cv2.TM_CCOEFF_NORMED,
    )
    _, score, _, max_loc = cv2.minMaxLoc(res)
    ox = x0 - max_loc[0]
    oy = y0 - max_loc[1]
    print(f"  template refine score={score:.3f} -> ({ox:.1f},{oy:.1f})")
    if score > 0.35:
        return float(ox), float(oy)
    return guess


def compose(placements: list[Placed]) -> np.ndarray:
    min_x = min(p.ox for p in placements)
    min_y = min(p.oy for p in placements)
    max_x = max(p.ox + p.image.shape[1] for p in placements)
    max_y = max(p.oy + p.image.shape[0] for p in placements)
    pad = 40
    w = int(max_x - min_x + 2 * pad)
    h = int(max_y - min_y + 2 * pad)
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[:] = (18, 28, 18)

    # Paint #6 first (left), then anchor #7 on top.
    order = sorted(placements, key=lambda p: (p.ox, p.name != "b3-07"))
    for p in order:
        x = int(round(p.ox - min_x + pad))
        y = int(round(p.oy - min_y + pad))
        ih, iw = p.image.shape[:2]
        region = canvas[y : y + ih, x : x + iw]
        mask = np.any(p.image > 12, axis=2)
        region[mask] = p.image[mask]
        canvas[y : y + ih, x : x + iw] = region
        label = p.name
        cv2.putText(canvas, label, (x + 8, y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 255, 180), 2)
        if p.beam:
            bx, by = p.beam
            cv2.drawMarker(
                canvas,
                (x + bx, y + by),
                (0, 255, 255),
                cv2.MARKER_CROSS,
                18,
                2,
            )
    return canvas


def load(name: str) -> np.ndarray:
    path = BATCH3 / name
    img = cv2.imread(str(path))
    assert img is not None, path
    return mask_pip(crop_map(img))


def stitch_07_06() -> np.ndarray:
    """Start from #7; place #6 to its left, aligned on trap blue beam."""
    img7 = load("b3-07.png")
    img6 = load("b3-06.png")

    beam7 = find_anchor(img7)
    beam6 = find_anchor(img6)

    ox6 = float(beam7[0] - beam6[0])
    oy6 = float(beam7[1] - beam6[1])

    print(f"b3-07 anchor {beam7}")
    print(f"b3-06 anchor {beam6}")
    print(f"b3-06 placement ({ox6:.1f}, {oy6:.1f}) — left of b3-07: {ox6 < 0}")

    placements = [
        Placed("b3-06", img6, ox6, oy6, beam6),
        Placed("b3-07", img7, 0.0, 0.0, beam7),
    ]
    return compose(placements)


def main() -> None:
    mosaic = stitch_07_06()
    cv2.imwrite(str(OUT), mosaic)
    print(f"wrote {OUT} ({mosaic.shape[1]}x{mosaic.shape[0]})")


if __name__ == "__main__":
    main()
