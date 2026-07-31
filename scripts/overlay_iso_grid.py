#!/usr/bin/env python3
"""Overlay tile grid locked to thick blue borders.

One-tile size is taken from the top-left blue zigzag (outer L arm),
then the whole lattice is phase-shifted so grid lines coincide with
border centerlines — not merely parallel.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PANO = ROOT / "assets" / "reference" / "bear-trap" / "panorama-stitching-batch3.png"
OUT = ROOT / "assets" / "reference" / "bear-trap" / "panorama-iso-grid.png"
CAL = ROOT / "assets" / "reference" / "bear-trap" / "iso-grid-cal.json"
DEBUG = ROOT / "assets" / "reference" / "bear-trap" / "stitching-debug"

# Screen px per world tile from stitch placements ↔ viewport centers.
MAT = np.array(
    [[95.70840124, -99.49624005], [-67.69089597, -68.09304851]],
    dtype=float,
)


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    assert n > 1e-9, "zero vector"
    return v / n


def draw_line(
    img: np.ndarray,
    nrm: np.ndarray,
    p: float,
    tang: np.ndarray,
    color: tuple[int, int, int],
    thickness: int,
) -> None:
    h, w = img.shape[:2]
    pt = p * nrm
    tx, ty = float(tang[0]), float(tang[1])
    ts: list[float] = []
    if abs(tx) > 1e-9:
        for x_edge in (0.0, float(w - 1)):
            t = (x_edge - pt[0]) / tx
            y = pt[1] + t * ty
            if -1 <= y <= h:
                ts.append(t)
    if abs(ty) > 1e-9:
        for y_edge in (0.0, float(h - 1)):
            t = (y_edge - pt[1]) / ty
            x = pt[0] + t * tx
            if -1 <= x <= w:
                ts.append(t)
    if len(ts) < 2:
        return
    t0, t1 = min(ts), max(ts)
    p0 = (int(pt[0] + t0 * tx), int(pt[1] + t0 * ty))
    p1 = (int(pt[0] + t1 * tx), int(pt[1] + t1 * ty))
    cv2.line(img, p0, p1, color, thickness, cv2.LINE_AA)


def thick_mask(pano: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(pano, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (90, 80, 140), (130, 255, 255))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    thick = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ker)
    return cv2.morphologyEx(thick, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))


def _arm_from_tip(
    hull: np.ndarray, tip: np.ndarray, direction: np.ndarray, min_len: float
) -> tuple[np.ndarray, int, float]:
    """Longest hull edge from tip aligned with ±direction → (end, n_tiles, align)."""
    ud = unit(direction)
    best = None
    for i in range(len(hull)):
        p0, p1 = hull[i], hull[(i + 1) % len(hull)]
        for a, b in ((p0, p1), (p1, p0)):
            if np.linalg.norm(a - tip) > 12:
                continue
            v = b - a
            ln = float(np.linalg.norm(v))
            if ln < min_len:
                continue
            align = float(np.dot(unit(v), ud))
            if best is None or abs(align) > abs(best[0]):
                best = (align, b, ln)
    assert best is not None and abs(best[0]) > 0.85, f"arm not found for {direction}; best={best}"
    end, ln = best[1], best[2]
    ref_len = float(np.linalg.norm(direction))
    n_tiles = max(1, int(round(ln / ref_len)))
    return end, n_tiles, float(best[0])


def zigzag_tip_and_arms(
    thick: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Tip + 1-tile points on X and Y arms of the top-left blue L."""
    x0, y0, ww, hh = 180, 40, 600, 550
    th = thick[y0 : y0 + hh, x0 : x0 + ww]
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    assert cnts, "no thick contours in top-left crop"
    c = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(float)
    c = c + np.array([x0, y0], dtype=float)
    tip = c[np.argmin(c[:, 0] + c[:, 1])]
    hull = cv2.convexHull(c.astype(np.float32)).reshape(-1, 2)

    end_x, n_x, _ = _arm_from_tip(hull, tip, MAT[:, 0], min_len=150)
    end_y, n_y, _ = _arm_from_tip(hull, tip, MAT[:, 1], min_len=150)
    one_x = tip + (end_x - tip) / n_x
    one_y = tip + (end_y - tip) / n_y
    return tip, one_x, one_y, end_x


def peak_offsets(pts: np.ndarray, nrm: np.ndarray, min_sep: float = 90) -> list[float]:
    proj = pts @ nrm
    lo, hi = float(proj.min()), float(proj.max())
    hist, edges = np.histogram(proj, bins=np.linspace(lo, hi, 220))
    hist = np.convolve(hist, np.ones(5) / 5, mode="same")
    peaks: list[tuple[float, float]] = []
    for i in range(2, len(hist) - 2):
        if hist[i] >= hist[i - 1] and hist[i] >= hist[i + 1] and hist[i] > hist.max() * 0.12:
            peaks.append((float(hist[i]), 0.5 * (edges[i] + edges[i + 1])))
    peaks.sort(reverse=True)
    kept: list[float] = []
    for _, p in peaks:
        if all(abs(p - k) >= min_sep for k in kept):
            kept.append(p)
    return sorted(kept)


def residual(p: float, origin: float, step: float) -> float:
    return (p - origin) / step - round((p - origin) / step)


def best_phase(peaks: list[float], step: float, prefer: float) -> tuple[float, float, float]:
    """Return (origin, rms, shift_tiles) minimizing border residuals near prefer."""
    best = (1e9, prefer, 0.0)
    for s in np.linspace(-0.5, 0.5, 401):
        origin = prefer + s * step
        res = [residual(p, origin, step) for p in peaks]
        rms = float(np.sqrt(np.mean(np.square(res))))
        score = rms + 0.02 * abs(s)
        if score < best[0]:
            best = (score, origin, rms, s)  # type: ignore[assignment]
    score, origin, rms, s = best  # type: ignore[misc]
    return float(origin), float(rms), float(s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pano", type=Path, default=PANO)
    parser.add_argument("-o", "--output", type=Path, default=OUT)
    parser.add_argument("--pad", type=int, default=50)
    args = parser.parse_args()

    pano = cv2.imread(str(args.pano))
    assert pano is not None, args.pano
    thick = thick_mask(pano)

    tip, one_x, one_y, end_x = zigzag_tip_and_arms(thick)
    tile_x = one_x - tip
    tile_y = one_y - tip
    # Prefer measured zigzag edges; fall back scale-check vs MAT.
    assert np.linalg.norm(tile_x) > 40 and np.linalg.norm(tile_y) > 40, (tile_x, tile_y)
    scale = float(np.linalg.norm(tile_x) / np.linalg.norm(MAT[:, 0]))

    ua, ub = unit(tile_x), unit(tile_y)
    na, nb = np.array([-ua[1], ua[0]]), np.array([-ub[1], ub[0]])
    if float(np.dot(na, tile_y)) < 0:
        na = -na
    if float(np.dot(nb, tile_x)) < 0:
        nb = -nb
    step_a = float(np.dot(tile_y, na))  # spacing for ΔY = 1
    step_b = float(np.dot(tile_x, nb))  # spacing for ΔX = 1
    assert step_a > 40 and step_b > 40, (step_a, step_b)

    # Phase = zigzag arms (exact blue outer edges) — same lines, not merely parallel.
    origin_a = float(tip @ na)  # X-arm is constant-na
    origin_b = float(tip @ nb)  # Y-arm is constant-nb
    arm_a_err = abs(float(end_x @ na) - origin_a)
    arm_b_err = abs(float(one_y @ nb) - origin_b)
    rms_a, rms_b = arm_a_err / step_a, arm_b_err / step_b
    shift_a = shift_b = 0.0

    ys, xs = np.where(thick > 0)
    pts = np.column_stack([xs.astype(float), ys.astype(float)])
    rng = np.random.default_rng(0)
    if len(pts) > 40000:
        pts = pts[rng.choice(len(pts), 40000, replace=False)]

    peaks_a = peak_offsets(pts, na)
    peaks_b = peak_offsets(pts, nb)
    border_i_a = {
        int(round((p - origin_a) / step_a))
        for p in peaks_a
        if abs(residual(p, origin_a, step_a)) < 0.2
    }
    border_i_b = {
        int(round((p - origin_b) / step_b))
        for p in peaks_b
        if abs(residual(p, origin_b, step_b)) < 0.2
    }
    border_i_a.add(0)
    border_i_b.add(0)

    base = pano.copy()
    pad = args.pad
    for i in range(-pad, pad + 100):
        p = origin_a + i * step_a
        if i in border_i_a:
            draw_line(base, na, p, ua, (255, 0, 255), 5)
            draw_line(base, na, p, ua, (0, 255, 255), 2)
        else:
            bold = i % 2 == 0
            draw_line(
                base,
                na,
                p,
                ua,
                (0, 255, 255) if bold else (0, 170, 170),
                2 if bold else 1,
            )
    for i in range(-pad, pad + 100):
        p = origin_b + i * step_b
        if i in border_i_b:
            draw_line(base, nb, p, ub, (255, 0, 255), 5)
            draw_line(base, nb, p, ub, (0, 255, 255), 2)
        else:
            bold = i % 2 == 0
            draw_line(
                base,
                nb,
                p,
                ub,
                (0, 255, 255) if bold else (0, 170, 170),
                2 if bold else 1,
            )

    # Measured one square at the zigzag tip (red).
    sq = np.array(
        [tip, tip + tile_x, tip + tile_x + tile_y, tip + tile_y],
        dtype=np.int32,
    )
    cv2.polylines(base, [sq], True, (0, 0, 255), 3, cv2.LINE_AA)
    for p in sq:
        cv2.circle(base, (int(p[0]), int(p[1])), 5, (0, 0, 255), -1)

    cv2.rectangle(base, (10, 10), (1020, 110), (0, 0, 0), -1)
    cv2.putText(
        base,
        "1 square = top-left blue zigzag (red)  |  grid SHIFTED onto thick borders",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 255),
        2,
    )
    cv2.putText(
        base,
        f"step {step_a:.1f}/{step_b:.1f}px  |edge|={np.linalg.norm(tile_x):.1f}/{np.linalg.norm(tile_y):.1f}"
        f"  arm phase err {rms_a:.3f}/{rms_b:.3f} tile",
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (0, 255, 255),
        1,
    )
    cv2.putText(
        base,
        "magenta under cyan = same line as thick border; bold = 2-tile (city)",
        (20, 95),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 0, 255),
        1,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    DEBUG.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), base)

    cx, cy = int(tip[0] + 80), int(tip[1] - 40)
    half = 260
    y0, y1 = max(0, cy - half), min(base.shape[0], cy + half)
    x0, x1 = max(0, cx - half), min(base.shape[1], cx + half)
    zoom = base[y0:y1, x0:x1]
    cv2.imwrite(str(DEBUG / "grid-zigzag-lock.png"), zoom)
    cv2.imwrite(str(DEBUG / "one-square-measure.png"), zoom)

    CAL.write_text(
        json.dumps(
            {
                "method": "zigzag_one_square_is_grid",
                "zigzag_tip": tip.tolist(),
                "zigzag_one_x": one_x.tolist(),
                "zigzag_one_y": one_y.tolist(),
                "tile_x": tile_x.tolist(),
                "tile_y": tile_y.tolist(),
                "step_a": step_a,
                "step_b": step_b,
                "origin_a": origin_a,
                "origin_b": origin_b,
                "arm_phase_err_tiles": [rms_a, rms_b],
                "scale_vs_mat": scale,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"1-square edge |tile_x|={np.linalg.norm(tile_x):.1f} |tile_y|={np.linalg.norm(tile_y):.1f}")
    print(f"step {step_a:.1f}/{step_b:.1f}  arm phase err {rms_a:.4f}/{rms_b:.4f} tile")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
