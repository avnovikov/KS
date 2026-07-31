#!/usr/bin/env python3
"""Build a panoramic mosaic from bear-trap screenshots (same zoom)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ks.placement.viewport_ocr import rel_key, scan_shots

ROOT = Path(__file__).resolve().parents[1]
BEAR_TRAP = ROOT / "assets" / "reference" / "bear-trap"
SHOTS = BEAR_TRAP / "blockers-shots"

BATCH_CONFIG = {
    "legacy": {
        "glob": lambda s: sorted(s.glob("shot-*.png")) + sorted((s / "batch2").glob("b2-*.png")),
        "viewport_yaml": BEAR_TRAP / "viewport-coords.yaml",
        "anchor_key": "shot-03.png",
        "anchor_world": (698, 816),
        "out_mosaic": BEAR_TRAP / "panorama-mosaic.png",
        "out_grid": BEAR_TRAP / "panorama-grid.png",
        "min_shots": 16,
    },
    "batch3": {
        "glob": lambda s: sorted((s / "batch3").glob("b3-*.png")),
        "viewport_yaml": BEAR_TRAP / "viewport-coords-batch3.yaml",
        "anchor_key": "batch3/b3-10.png",
        "anchor_world": (698, 816),
        "out_mosaic": BEAR_TRAP / "panorama-mosaic-batch3.png",
        "out_grid": BEAR_TRAP / "panorama-grid-batch3.png",
        "min_shots": 12,
    },
}

@dataclass
class Shot:
    key: str
    path: Path
    cx: int
    cy: int
    image: np.ndarray


def list_shots(cfg: dict) -> list[Path]:
    paths = cfg["glob"](SHOTS)
    assert len(paths) >= cfg["min_shots"], f"expected >={cfg['min_shots']} shots, got {len(paths)}"
    return paths


def load_viewport_yaml(yaml_path: Path) -> dict[str, tuple[int, int]]:
    import yaml

    data = yaml.safe_load(yaml_path.read_text()) or {}
    viewport = data.get("viewport", {})
    return {k: (int(v["x"]), int(v["y"])) for k, v in viewport.items()}


def crop_map(img: np.ndarray) -> np.ndarray:
    """Keep the map band; drop top HUD and bottom nav/chat."""
    h, w = img.shape[:2]
    square = abs(h - w) < max(h, w) * 0.05
    if square:
        # Google Photos square export (2000×2000)
        return img[int(h * 0.12) : int(h * 0.78), int(w * 0.06) : int(w * 0.94)]
    return img[int(h * 0.14) : int(h * 0.72), int(w * 0.06) : int(w * 0.94)]


def coord_offset(c_from: tuple[int, int], c_to: tuple[int, int], px: float, py: float) -> tuple[float, float]:
    """Screen offset to place *to* image relative to *from* (same zoom)."""
    dx = -((c_to[0] - c_to[1]) - (c_from[0] - c_from[1])) * px
    dy = -((c_to[0] + c_to[1]) - (c_from[0] + c_from[1])) * py
    return dx, dy


def refine_translation(
    img_from: np.ndarray,
    img_to: np.ndarray,
    guess: tuple[float, float],
    search: int = 80,
) -> tuple[tuple[float, float], int]:
    """Refine placement of img_to relative to img_from via ORB + RANSAC."""
    g1 = cv2.cvtColor(img_from, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(img_to, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=6000)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    if d1 is None or d2 is None:
        return guess, 0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = bf.knnMatch(d1, d2, k=2)
    good = [m for m, n in matches if m.distance < 0.75 * n.distance]
    if len(good) < 16:
        return guess, len(good)

    pts1 = np.float32([k1[m.queryIdx].pt for m in good])
    pts2 = np.float32([k2[m.trainIdx].pt for m in good])
    disp = pts1 - pts2  # offset for img_to

    gx, gy = guess
    dist = np.linalg.norm(disp - np.array([gx, gy]), axis=1)
    near = disp[dist <= search]
    if len(near) < 12:
        near = disp

    refined = tuple(np.median(near, axis=0))
    err = np.linalg.norm(near - refined, axis=1)
    inliers = int((err < 4.0).sum())
    if inliers < 12:
        return guess, inliers
    return (float(refined[0]), float(refined[1])), inliers


def default_scale(shots: list[Shot]) -> float:
    mw = float(np.median([s.image.shape[1] for s in shots]))
    return mw / 17.5  # ~17 tiles across the map band at this zoom


def calibrate_scale(shots: list[Shot], px0: float) -> tuple[float, float]:
    by_key = {s.key: s for s in shots}
    samples_x: list[float] = []
    samples_y: list[float] = []

    for a in by_key:
        for c in by_key:
            if a >= c:
                continue
            da = abs(by_key[a].cx - by_key[c].cx) + abs(by_key[a].cy - by_key[c].cy)
            if da > 10 or da < 2:
                continue
            guess = coord_offset((by_key[a].cx, by_key[a].cy), (by_key[c].cx, by_key[c].cy), px0, px0)
            if abs(guess[0]) + abs(guess[1]) < 20:
                continue
            off, inl = refine_translation(by_key[a].image, by_key[c].image, guess, search=140)
            if inl < 24:
                continue
            iso_x = (by_key[c].cx - by_key[c].cy) - (by_key[a].cx - by_key[a].cy)
            iso_y = (by_key[c].cx + by_key[c].cy) - (by_key[a].cx + by_key[a].cy)
            if iso_x:
                samples_x.append(off[0] / iso_x)
            if iso_y:
                samples_y.append(off[1] / iso_y)

    px = float(np.median(samples_x)) if samples_x else px0
    py = float(np.median(samples_y)) if samples_y else px
    if abs(px) < 8:
        px = px0
    if abs(py) < 8:
        py = px0
    return px, py


def accept_refined(
    guess: tuple[float, float],
    refined: tuple[float, float],
    inliers: int,
    *,
    min_inliers: int = 40,
    max_delta: float = 90.0,
) -> tuple[float, float]:
    if inliers < min_inliers:
        return guess
    delta = np.hypot(refined[0] - guess[0], refined[1] - guess[1])
    if delta > max_delta:
        return guess
    return refined


def build_positions(
    shots: list[Shot], px: float, py: float, *, anchor_key: str
) -> dict[str, tuple[float, float]]:
    by_key = {s.key: s for s in shots}
    anchor = by_key[anchor_key]
    positions: dict[str, tuple[float, float]] = {}

    for key, shot in by_key.items():
        guess = (0.0, 0.0) if key == anchor_key else coord_offset(
            (anchor.cx, anchor.cy), (shot.cx, shot.cy), px, py
        )
        positions[key] = guess
        if key != anchor_key:
            print(f"  {key}: viewport ({shot.cx},{shot.cy}) -> {guess}")

    for key, shot in by_key.items():
        if key == anchor_key:
            continue
        d = abs(shot.cx - anchor.cx) + abs(shot.cy - anchor.cy)
        if d > 8:
            continue
        guess = positions[key]
        off, inl = refine_translation(anchor.image, shot.image, guess, search=80)
        positions[key] = accept_refined(guess, off, inl, min_inliers=50, max_delta=60.0)
        print(f"  refine {key}: inliers={inl} -> {positions[key]}")

    return positions


def compose(
    shots: list[Shot],
    positions: dict[str, tuple[float, float]],
    *,
    anchor_world: tuple[int, int],
) -> np.ndarray:
    by_key = {s.key: s for s in shots}
    placements: list[tuple[float, float, np.ndarray, str, int]] = []
    for s in shots:
        ox, oy = positions[s.key]
        placements.append((ox, oy, s.image, s.key, abs(s.cx - anchor_world[0]) + abs(s.cy - anchor_world[1])))

    min_x = min(o for o, _, _, _, _ in placements)
    min_y = min(o for _, o, _, _, _ in placements)
    max_x = max(o + im.shape[1] for o, _, im, _, _ in placements)
    max_y = max(o + im.shape[0] for _, o, im, _, _ in placements)
    pad = 30
    w = int(max_x - min_x + 2 * pad)
    h = int(max_y - min_y + 2 * pad)
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[:] = (18, 28, 18)

    # Farther from trap first; anchor neighborhood paints on top.
    for ox, oy, img, key, dist in sorted(placements, key=lambda t: t[4], reverse=True):
        x = int(round(ox - min_x + pad))
        y = int(round(oy - min_y + pad))
        h_i, w_i = img.shape[:2]
        region = canvas[y : y + h_i, x : x + w_i]
        mask = np.any(img > 12, axis=2)
        region[mask] = img[mask]
        canvas[y : y + h_i, x : x + w_i] = region
        shot = by_key[key]
        label = f"{Path(key).stem} ({shot.cx},{shot.cy})"
        cv2.putText(canvas, label, (x + 6, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 255, 180), 1, cv2.LINE_AA)

    return canvas


def build_contact_grid(shots: list[Shot]) -> np.ndarray:
    entries = sorted(((s.cy, s.cx, s) for s in shots), key=lambda t: (t[0], t[1]))
    cols = 4
    rows = (len(entries) + cols - 1) // cols
    thumb = cv2.resize(entries[0][2].image, (340, 510))
    cell_h, cell_w = thumb.shape[:2]
    grid = np.zeros((rows * cell_h + 24, cols * cell_w + 24, 3), dtype=np.uint8)
    grid[:] = (18, 28, 18)
    for i, (_cy, _cx, s) in enumerate(entries):
        r, c = divmod(i, cols)
        y = 12 + r * cell_h
        x = 12 + c * cell_w
        t = cv2.resize(s.image, (cell_w, cell_h))
        cv2.putText(t, Path(s.key).stem, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 80), 2)
        cv2.putText(
            t,
            f"X:{s.cx} Y:{s.cy}",
            (8, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (180, 255, 180),
            1,
        )
        grid[y : y + cell_h, x : x + cell_w] = t
    return grid


def load_shots(viewport: dict[str, tuple[int, int]], cfg: dict) -> list[Shot]:
    shots: list[Shot] = []
    for path in list_shots(cfg):
        key = rel_key(path, SHOTS)
        cx, cy = viewport[key]
        img = cv2.imread(str(path))
        assert img is not None, path
        shots.append(Shot(key=key, path=path, cx=cx, cy=cy, image=crop_map(img)))
    return shots


def main() -> None:
    parser = argparse.ArgumentParser(description="Stitch bear-trap screenshots into a panorama")
    parser.add_argument(
        "--batch",
        choices=sorted(BATCH_CONFIG),
        default="legacy",
        help="Which screenshot set to stitch (default: legacy)",
    )
    parser.add_argument(
        "--refresh-ocr",
        action="store_true",
        help="Re-scan search-bar coords with tesseract and rewrite viewport yaml",
    )
    args = parser.parse_args()
    cfg = BATCH_CONFIG[args.batch]

    if args.refresh_ocr:
        import yaml

        scanned = scan_shots(SHOTS)
        cfg["viewport_yaml"].write_text(yaml.safe_dump({"viewport": scanned}, sort_keys=True))
        print(f"refreshed {cfg['viewport_yaml']}")

    viewport = load_viewport_yaml(cfg["viewport_yaml"])
    shots = load_shots(viewport, cfg)
    print(f"Batch {args.batch}: {len(shots)} screenshots")

    px0 = default_scale(shots)
    py0 = px0 * 0.5
    print(f"Default scale px0={px0:.2f} py0={py0:.2f}")
    print("Calibrating horizontal scale…")
    px, _ = calibrate_scale(shots, px0)
    py = px * 0.5
    print(f"  px={px:.2f} py={py:.2f}")

    print("Placing shots…")
    positions = build_positions(shots, px, py, anchor_key=cfg["anchor_key"])

    mosaic = compose(shots, positions, anchor_world=cfg["anchor_world"])
    cv2.imwrite(str(cfg["out_mosaic"]), mosaic)
    print(f"wrote {cfg['out_mosaic']} ({mosaic.shape[1]}x{mosaic.shape[0]})")

    grid = build_contact_grid(shots)
    cv2.imwrite(str(cfg["out_grid"]), grid)
    print(f"wrote {cfg['out_grid']} ({grid.shape[1]}x{grid.shape[0]})")


if __name__ == "__main__":
    main()
