#!/usr/bin/env python3
"""Build a before/after lighting normalization preview from live capture bands."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from ks.cartograph.lighting import (
    apply_log_chrom_shift,
    estimate_log_chrom_shift,
    load_lighting_reference,
    normalize_band_lighting,
)


def _find_bands(indir: Path) -> list[Path]:
    bands = sorted(indir.glob("band-*.png"))
    return bands if bands else sorted(indir.glob("*.png"))[:6]


def _label(img: np.ndarray, text: str) -> np.ndarray:
    out = img.copy()
    cv2.putText(
        out,
        text,
        (12, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("artifacts/cartograph-live"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/cartograph-live/lighting-preview.png"),
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("assets/reference/cartograph/lighting-reference.png"),
    )
    args = parser.parse_args()

    load_lighting_reference.cache_clear()
    ref = cv2.imread(str(args.reference))
    if ref is None:
        raise SystemExit(f"reference not found: {args.reference}")

    bands = _find_bands(args.input_dir)
    if not bands:
        raise SystemExit(f"no band PNGs in {args.input_dir}")

    # Pick up to 3 non-reference bands for comparison.
    samples = [cv2.imread(str(p), cv2.IMREAD_COLOR) for p in bands[:3]]
    samples = [s for s in samples if s is not None]
    if not samples:
        raise SystemExit("failed to load band images")

    panels: list[np.ndarray] = []
    h_ref, w_ref = ref.shape[:2]
    for i, raw in enumerate(samples):
        if raw.shape[:2] != (h_ref, w_ref):
            raw = cv2.resize(raw, (w_ref, h_ref))
        du, dv = estimate_log_chrom_shift(raw, ref)
        chrom_only = apply_log_chrom_shift(raw, du, dv)
        full = normalize_band_lighting(raw)
        panels.append(_label(raw, f"raw #{i + 1}"))
        panels.append(_label(chrom_only, f"log-chrom #{i + 1}"))
        panels.append(_label(full, f"full norm #{i + 1}"))

    ref_panel = _label(ref, "reference")
    row_h = h_ref
    row1 = np.hstack([ref_panel] + panels[:3])
    rows = [row1]
    for start in range(3, len(panels), 3):
        chunk = panels[start : start + 3]
        pad = ref_panel.copy()
        pad[:, :] = 0
        cv2.putText(
            pad,
            "...",
            (12, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (128, 128, 128),
            2,
            cv2.LINE_AA,
        )
        row = np.hstack([pad] + chunk)
        rows.append(row)

    out_img = rows[0]
    for row in rows[1:]:
        if row.shape[1] != out_img.shape[1]:
            row = cv2.resize(row, (out_img.shape[1], row_h))
        out_img = np.vstack([out_img, row])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), out_img)
    print(f"wrote {args.output} ({out_img.shape[1]}x{out_img.shape[0]})")


if __name__ == "__main__":
    main()
