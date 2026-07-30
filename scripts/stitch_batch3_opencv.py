#!/usr/bin/env python3
"""Stitch batch3 bear-trap screenshots with OpenCV SCANS (affine / map pan).

Pairwise chain: stitch two images at a time, growing the panorama left or right
based on viewport coords so SCANS gets images in the correct order.

See: https://docs.opencv.org/4.x/d8/d19/tutorial_stitcher.html
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
BATCH3 = ROOT / "assets" / "reference" / "bear-trap" / "blockers-shots" / "batch3"
BATCH3_CROPPED = ROOT / "assets" / "reference" / "bear-trap" / "blockers-shots" / "batch3-cropped"
COORDS = ROOT / "assets" / "reference" / "bear-trap" / "viewport-coords-batch3.yaml"
OUT = ROOT / "assets" / "reference" / "bear-trap" / "panorama-stitching-batch3.png"
DEBUG_DIR = ROOT / "assets" / "reference" / "bear-trap" / "stitching-debug"

# Start from the pair that looked best in manual trials (west → east).
DEFAULT_SEED = ("b3-06.png", "b3-07.png")


# UI mask + crop calibrated from user FIXED reference (b3-07).
# Rects are (x0, y0, x1, y1) as fractions of native 1080×2424.
MASK_COLOR = (0, 0, 0)
MASK_RECTS = [
    (0.0000, 0.0000, 1.0000, 0.1787),  # top status / resources / teleport
    (0.0000, 0.1787, 0.3355, 0.2842),  # left marching panel
    (0.0000, 0.4463, 0.0504, 0.5137),  # left edge tab
    (0.8772, 0.1787, 1.0000, 0.4443),  # right event icon column
    (0.0000, 0.6963, 0.2478, 0.8662),  # bottom-left PiP phone
    (0.8728, 0.7783, 1.0000, 0.8662),  # bottom-right compass/mail
    (0.0000, 0.8662, 1.0000, 1.0000),  # bottom nav bar
]
# After masking, drop solid top/bottom black bars.
CROP_TOP = 0.1787
CROP_BOTTOM = 0.8662
CROP_LEFT = 0.0
CROP_RIGHT = 1.0


def _frac_rect(h: int, w: int, box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (
        int(round(w * x0)),
        int(round(h * y0)),
        int(round(w * x1)),
        int(round(h * y1)),
    )


def mask_game_ui(img: np.ndarray) -> np.ndarray:
    """Black out HUD chrome using the user-calibrated FIXED boxes."""
    out = img.copy()
    h, w = out.shape[:2]
    for box in MASK_RECTS:
        x0, y0, x1, y1 = _frac_rect(h, w, box)
        cv2.rectangle(out, (x0, y0), (x1, y1), MASK_COLOR, -1)
    return out


def crop_map_window(img: np.ndarray) -> np.ndarray:
    """Crop away solid top/bottom UI bands after masking."""
    h, w = img.shape[:2]
    y0 = int(round(h * CROP_TOP))
    y1 = int(round(h * CROP_BOTTOM))
    x0 = int(round(w * CROP_LEFT))
    x1 = int(round(w * CROP_RIGHT))
    assert y1 > y0 and x1 > x0, f"invalid crop {(x0, y0, x1, y1)} on {w}x{h}"
    return img[y0:y1, x0:x1].copy()


def crop_map(img: np.ndarray) -> np.ndarray:
    """Mask HUD, then crop to the map window."""
    return crop_map_window(mask_game_ui(img))


def load(name: str) -> np.ndarray:
    path = BATCH3 / name
    img = cv2.imread(str(path))
    assert img is not None, path
    return crop_map(img)


def load_viewport() -> dict[str, tuple[int, int]]:
    raw = yaml.safe_load(COORDS.read_text(encoding="utf-8"))
    out: dict[str, tuple[int, int]] = {}
    for key, val in raw.get("viewport", {}).items():
        name = Path(key).name
        out[name] = (int(val["x"]), int(val["y"]))
    return out


def chain_order_from_coords(
    viewport: dict[str, tuple[int, int]],
    *,
    seed: tuple[str, str],
    row_y_tol: int = 6,
) -> list[str]:
    """Build stitch order: seed pair, then expand east/west on same row, then other rows."""
    assert seed[0] in viewport and seed[1] in viewport, seed
    used = {seed[0], seed[1]}
    order = [seed[0], seed[1]]
    anchor_y = (viewport[seed[0]][1] + viewport[seed[1]][1]) // 2

    def same_row(name: str) -> bool:
        return abs(viewport[name][1] - anchor_y) <= row_y_tol

    remaining = [n for n in viewport if n not in used]

    def pick_extreme(east: bool) -> str | None:
        candidates = [n for n in remaining if same_row(n)]
        if not candidates:
            return None
        if east:
            return max(candidates, key=lambda n: viewport[n][0])
        return min(candidates, key=lambda n: viewport[n][0])

    # Expand east then west along the trap row.
    while True:
        nxt = pick_extreme(east=True)
        if nxt is None:
            break
        order.append(nxt)
        used.add(nxt)
        remaining.remove(nxt)

    west = seed[0]
    while True:
        nxt = pick_extreme(east=False)
        if nxt is None:
            break
        order.insert(0, nxt)
        used.add(nxt)
        remaining.remove(nxt)

    # Remaining shots: nearest viewport coord to current chain ends.
    while remaining:
        left_xy = viewport[order[0]]
        right_xy = viewport[order[-1]]

        def dist_to_chain(name: str) -> float:
            xy = viewport[name]
            dl = (xy[0] - left_xy[0]) ** 2 + (xy[1] - left_xy[1]) ** 2
            dr = (xy[0] - right_xy[0]) ** 2 + (xy[1] - right_xy[1]) ** 2
            return min(dl, dr)

        nxt = min(remaining, key=dist_to_chain)
        order.append(nxt)
        used.add(nxt)
        remaining.remove(nxt)

    return order


def stitch_pair(a: np.ndarray, b: np.ndarray) -> tuple[int, np.ndarray | None]:
    stitcher = cv2.Stitcher.create(cv2.Stitcher_SCANS)
    status, pano = stitcher.stitch([a, b])
    return status, pano if status == cv2.Stitcher_OK else None


def chain_stitch(
    images: list[np.ndarray],
    names: list[str],
    viewport: dict[str, tuple[int, int]],
    *,
    debug_dir: Path | None,
    start_at: int = 2,
) -> np.ndarray:
    assert len(images) == len(names) >= 2, "need at least two images"
    pano = images[0]
    chain_names = [names[0]]

    for i in range(1, len(images)):
        step = i + 1
        if step < start_at:
            pano = images[i] if i == 1 else pano
            chain_names.append(names[i])
            continue

        prev_name = chain_names[-1]
        nxt_name = names[i]
        prev_xy = viewport[prev_name]
        nxt_xy = viewport[nxt_name]

        # SCANS expects left image first when panning east.
        if nxt_xy[0] >= prev_xy[0]:
            left, right = pano, images[i]
            tag = f"{Path(prev_name).stem}+{Path(nxt_name).stem}"
        else:
            left, right = images[i], pano
            tag = f"{Path(nxt_name).stem}+{Path(prev_name).stem}"

        status, merged = stitch_pair(left, right)
        if merged is None:
            raise RuntimeError(
                f"stitch failed at step {step} ({prev_name} + {nxt_name}), status={status}"
            )

        w, h = merged.shape[1], merged.shape[0]
        print(f"  step {step:02d}: {tag} -> {w}x{h}")
        pano = merged
        chain_names.append(nxt_name)

        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            out_path = debug_dir / f"step-{step:02d}-{tag}.png"
            cv2.imwrite(str(out_path), pano)
            print(f"           saved {out_path.relative_to(ROOT)}")

    return pano


def main() -> None:
    parser = argparse.ArgumentParser(description="Stitch batch3 with OpenCV SCANS (pairwise chain)")
    parser.add_argument(
        "--order",
        nargs="+",
        help="Explicit stitch order (filenames). Default: auto from viewport coords + seed pair.",
    )
    parser.add_argument(
        "--seed",
        nargs=2,
        metavar=("A", "B"),
        default=DEFAULT_SEED,
        help=f"Seed pair for auto order (default: {' '.join(DEFAULT_SEED)})",
    )
    parser.add_argument(
        "--pair",
        nargs=2,
        metavar=("A", "B"),
        help="Stitch only two images, e.g. --pair b3-06.png b3-07.png",
    )
    parser.add_argument(
        "--start-at",
        type=int,
        default=2,
        help="Resume chain from step N (1-based; step 1 is first image only)",
    )
    parser.add_argument(
        "--debug-dir",
        type=Path,
        default=DEBUG_DIR,
        help="Save intermediate panorama after each pairwise stitch",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Do not write intermediate step PNGs",
    )
    parser.add_argument(
        "--preview-masks",
        type=Path,
        nargs="?",
        const=BATCH3_CROPPED,
        metavar="DIR",
        help=f"Write mask+cropped PNGs (default: {BATCH3_CROPPED.relative_to(ROOT)})",
    )
    parser.add_argument("-o", "--output", type=Path, default=OUT)
    args = parser.parse_args()

    if args.preview_masks:
        out_dir = args.preview_masks if args.preview_masks.is_absolute() else ROOT / args.preview_masks
        out_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(BATCH3.glob("b3-*.png")):
            img = cv2.imread(str(path))
            assert img is not None, path
            cropped = crop_map(img)
            out_path = out_dir / path.name
            cv2.imwrite(str(out_path), cropped)
            print(f"wrote {out_path.relative_to(ROOT)} ({cropped.shape[1]}x{cropped.shape[0]})")
        return

    viewport = load_viewport()

    if args.pair:
        names = list(args.pair)
    elif args.order:
        names = args.order
    else:
        names = chain_order_from_coords(viewport, seed=tuple(args.seed))
        print("Auto stitch order (seed + coord expansion):")
        for i, n in enumerate(names, start=1):
            x, y = viewport[n]
            print(f"  {i:2d}. {n}  ({x}, {y})")

    images = [load(n) for n in names]
    debug_dir = None if args.no_debug else args.debug_dir

    print(f"Stitching {len(images)} images (OpenCV SCANS, pairwise)…")
    if len(images) == 1:
        pano = images[0]
    elif len(images) == 2:
        a_xy = viewport[names[0]]
        b_xy = viewport[names[1]]
        if b_xy[0] >= a_xy[0]:
            status, pano = stitch_pair(images[0], images[1])
        else:
            status, pano = stitch_pair(images[1], images[0])
        if pano is None:
            raise SystemExit(f"stitch failed, status={status}")
        print(f"  pair result: {pano.shape[1]}x{pano.shape[0]}")
    else:
        pano = chain_stitch(
            images,
            names,
            viewport,
            debug_dir=debug_dir,
            start_at=args.start_at,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), pano)
    print(f"wrote {args.output} ({pano.shape[1]}x{pano.shape[0]})")


if __name__ == "__main__":
    main()
