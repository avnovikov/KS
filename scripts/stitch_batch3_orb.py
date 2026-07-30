#!/usr/bin/env python3
"""Stitch batch3-cropped shots via pairwise ORB offsets (skip b3-04 / b3-05 by default).

Uses confirmed element matches as pair hints; estimates translation with ORB+RANSAC,
places all images in one canvas. OpenCV SCANS is used only as a sanity check pair-test.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CROPPED = ROOT / "assets" / "reference" / "bear-trap" / "blockers-shots" / "batch3-cropped"
OUT = ROOT / "assets" / "reference" / "bear-trap" / "panorama-stitching-batch3.png"

# Pairwise links from element inventory.
# 04/05 sit ABOVE the left (west) band — follow blue territory lines (not south of trap).
DEFAULT_PAIRS = [
    ("b3-09.png", "b3-10.png"),  # woodmill_trap + moose
    ("b3-10.png", "b3-01.png"),  # trap + ACE
    ("b3-01.png", "b3-11.png"),  # woodmill_hq + ACE
    ("b3-01.png", "b3-02.png"),  # 02 left of 01
    ("b3-02.png", "b3-03.png"),  # 03 further left
    ("b3-11.png", "b3-02.png"),
    ("b3-06.png", "b3-07.png"),  # HQ + iron
    ("b3-01.png", "b3-06.png"),  # woodmill_hq
    ("b3-11.png", "b3-12.png"),  # mill_lv6
    ("b3-12.png", "b3-03.png"),
    ("b3-07.png", "b3-09.png"),  # woodmill_trap
    ("b3-07.png", "b3-08.png"),  # iron_mine
    ("b3-06.png", "b3-11.png"),  # woodmill_hq
    # 04 / 05 — above left part along territory border (do NOT link 01→04; that pulls south)
    ("b3-03.png", "b3-04.png"),
    ("b3-02.png", "b3-04.png"),
    ("b3-02.png", "b3-05.png"),
    ("b3-03.png", "b3-05.png"),
    ("b3-04.png", "b3-05.png"),  # shared Lv2 wolf on border
]

SOUTH_PAIRS: list[tuple[str, str]] = []  # unused; 04/05 are north-west, not south


def load(name: str) -> np.ndarray:
    path = CROPPED / name
    img = cv2.imread(str(path))
    assert img is not None, path
    return img


def orb_offset(a: np.ndarray, b: np.ndarray) -> tuple[float, float, int] | None:
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    ma = (ga > 20).astype(np.uint8) * 255
    mb = (gb > 20).astype(np.uint8) * 255
    orb = cv2.ORB_create(8000)
    ka, da = orb.detectAndCompute(ga, ma)
    kb, db = orb.detectAndCompute(gb, mb)
    if da is None or db is None:
        return None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(da, db, k=2)
    good = []
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.7 * n.distance:
            good.append(m)
    if len(good) < 15:
        return None
    pts_a = np.float32([ka[m.queryIdx].pt for m in good])
    pts_b = np.float32([kb[m.trainIdx].pt for m in good])
    M, inl = cv2.estimateAffinePartial2D(
        pts_b, pts_a, method=cv2.RANSAC, ransacReprojThreshold=4.0
    )
    if M is None or inl is None or int(inl.sum()) < 12:
        return None
    scale = float(np.hypot(M[0, 0], M[0, 1]))
    if not (0.92 < scale < 1.08):
        return None
    return float(M[0, 2]), float(M[1, 2]), int(inl.sum())


def compose(placements: list[tuple[np.ndarray, float, float]]) -> np.ndarray:
    boxes = []
    for img, ox, oy in placements:
        h, w = img.shape[:2]
        boxes.append((img, int(np.floor(ox)), int(np.floor(oy)), w, h))
    minx = min(x for _, x, y, w, h in boxes)
    miny = min(y for _, x, y, w, h in boxes)
    maxx = max(x + w for _, x, y, w, h in boxes)
    maxy = max(y + h for _, x, y, w, h in boxes)
    canvas = np.zeros((maxy - miny, maxx - minx, 3), dtype=np.uint8)
    acc = np.zeros(canvas.shape[:2], dtype=np.float32)
    for img, x0, y0, w, h in boxes:
        x, y = x0 - minx, y0 - miny
        roi = canvas[y : y + h, x : x + w]
        wt = acc[y : y + h, x : x + w]
        hh, ww = roi.shape[:2]
        img_use = img[:hh, :ww]
        mask = img_use.sum(axis=2) > 30
        for c in range(3):
            dst = roi[:, :, c].astype(np.float32)
            src = img_use[:, :, c].astype(np.float32)
            both = mask & (wt > 0)
            only = mask & (wt == 0)
            dst[both] = (dst[both] + src[both]) * 0.5
            dst[only] = src[only]
            roi[:, :, c] = dst.astype(np.uint8)
        wt[mask] += 1
        canvas[y : y + hh, x : x + ww] = roi
        acc[y : y + hh, x : x + ww] = wt
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="ORB pairwise stitch of batch3-cropped")
    parser.add_argument(
        "--include-south",
        action="store_true",
        help="(deprecated) 04/05 are included by default above the left band",
    )
    parser.add_argument("-o", "--output", type=Path, default=OUT)
    args = parser.parse_args()

    pairs = list(DEFAULT_PAIRS)
    if args.include_south:
        pairs.extend(SOUTH_PAIRS)

    edges: list[tuple[str, str, float, float, int]] = []
    for a, b in pairs:
        off = orb_offset(load(a), load(b))
        if off is None:
            print(f"FAIL {Path(a).stem}->{Path(b).stem}")
            continue
        dx, dy, n = off
        if abs(dx) > 1600 or abs(dy) > 1600:
            print(f"DROP {Path(a).stem}->{Path(b).stem} dx={dx:.1f} dy={dy:.1f} in={n}")
            continue
        print(f"OK   {Path(a).stem}->{Path(b).stem} dx={dx:.1f} dy={dy:.1f} in={n}")
        edges.append((a, b, dx, dy, n))

    edges.sort(key=lambda e: -e[4])
    adj: dict[str, list[tuple[str, float, float, int]]] = defaultdict(list)
    for a, b, dx, dy, n in edges:
        adj[a].append((b, dx, dy, n))
        adj[b].append((a, -dx, -dy, n))

    origin = "b3-01.png"
    pos: dict[str, tuple[float, float]] = {origin: (0.0, 0.0)}
    q: deque[str] = deque([origin])
    while q:
        cur = q.popleft()
        ox, oy = pos[cur]
        for nxt, dx, dy, _n in sorted(adj[cur], key=lambda t: -t[3]):
            if nxt in pos:
                continue
            pos[nxt] = (ox + dx, oy + dy)
            q.append(nxt)

    print("placed:", ", ".join(sorted(Path(n).stem for n in pos)))
    placements = [(load(n), pos[n][0], pos[n][1]) for n in pos]
    pano = compose(placements)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), pano)
    print(f"wrote {args.output} ({pano.shape[1]}x{pano.shape[0]})")


if __name__ == "__main__":
    main()
