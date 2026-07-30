"""Cartograph orchestration: dry-run, fixture, and live entry points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from ks.cartograph.dedupe import dedupe_hits
from ks.cartograph.labels import extract_labels, hits_from_label_boxes
from ks.cartograph.mask import MaskConfig, mask_and_crop
from ks.cartograph.models import StructureHit
from ks.cartograph.sweep import JumpPlan, plan_jumps


# Default MAT from bear-trap stitch×viewport fit (FINDINGS / ocr-calibration).
DEFAULT_MAT = np.array(
    [[95.70840124, -99.49624005], [-67.69089597, -68.09304851]],
    dtype=float,
)


@dataclass(frozen=True)
class CartographResult:
    center: tuple[int, int]
    radius: int
    plan: JumpPlan
    hits: list[StructureHit]
    out_yaml: Path | None = None


def mask_config_from_calibration(path: Path) -> MaskConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mask = raw.get("mask") or {}
    rects = tuple(
        (float(r["x0"]), float(r["y0"]), float(r["x1"]), float(r["y1"]))
        for r in mask.get("rects", [])
    )
    return MaskConfig(
        rects=rects,
        crop_top=float(mask.get("crop_top", 0.0)),
        crop_bottom=float(mask.get("crop_bottom", 1.0)),
        crop_left=float(mask.get("crop_left", 0.0)),
        crop_right=float(mask.get("crop_right", 1.0)),
    )


def load_viewports_yaml(path: Path) -> dict[str, tuple[int, int]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    vp = raw.get("viewport") or raw
    out: dict[str, tuple[int, int]] = {}
    for key, val in vp.items():
        if not isinstance(val, dict):
            continue
        name = Path(str(key)).stem
        out[name] = (int(val["x"]), int(val["y"]))
    return out


def dry_run_plan(
    cx: int,
    cy: int,
    radius: int = 30,
    step: int = 10,
) -> JumpPlan:
    return plan_jumps(cx, cy, radius, step)


def hits_to_blockers_yaml(hits: list[StructureHit]) -> str:
    blocks = []
    for i, h in enumerate(hits):
        blocks.append(
            {
                "id": h.id or f"{h.kind}_{i}_{h.x}_{h.y}",
                "x": h.x,
                "y": h.y,
                "w": h.w,
                "h": h.h,
                "kind": h.kind,
                "note": h.label,
            }
        )
    return yaml.safe_dump(
        {"blocks": blocks, "source": "cartograph"},
        sort_keys=False,
        allow_unicode=True,
    )


def run_fixture_dir(
    fixture_dir: Path,
    *,
    viewports: dict[str, tuple[int, int]],
    mask_cfg: MaskConfig,
    radius: int = 30,
    step: int = 10,
    mat: np.ndarray = DEFAULT_MAT,
    out_yaml: Path | None = None,
    label_boxes_by_stem: dict[str, list[tuple[str, float, float]]] | None = None,
) -> CartographResult:
    """Process a folder of screenshots offline (no ADB).

    If ``label_boxes_by_stem`` is omitted, label OCR stub returns no hits
    (pipeline still validates mask/crop + plan around mean viewport).
    """
    assert fixture_dir.is_dir(), fixture_dir
    stems = sorted(viewports)
    assert stems, "no viewports provided"

    # Center = mean of provided viewports (fixture stand-in for "current view").
    cx = int(round(sum(viewports[s][0] for s in stems) / len(stems)))
    cy = int(round(sum(viewports[s][1] for s in stems) / len(stems)))
    plan = plan_jumps(cx, cy, radius, step)

    all_hits: list[StructureHit] = []
    import cv2

    for path in sorted(fixture_dir.glob("*.png")):
        stem = path.stem
        if stem not in viewports:
            continue
        img = cv2.imread(str(path))
        assert img is not None, path
        band = mask_and_crop(img, mask_cfg)
        ch, cw = band.shape[:2]
        crop_center = (cw / 2.0, ch / 2.0)
        boxes = (label_boxes_by_stem or {}).get(stem)
        if boxes is None:
            boxes = extract_labels(band)
        all_hits.extend(
            hits_from_label_boxes(
                boxes,
                viewport=viewports[stem],
                crop_center=crop_center,
                mat=mat,
                source=stem,
            )
        )

    merged = dedupe_hits(all_hits)
    if out_yaml is not None:
        out_yaml.parent.mkdir(parents=True, exist_ok=True)
        out_yaml.write_text(hits_to_blockers_yaml(merged), encoding="utf-8")

    return CartographResult(
        center=(cx, cy),
        radius=radius,
        plan=plan,
        hits=merged,
        out_yaml=out_yaml,
    )


def bluestacks_mask_config() -> MaskConfig:
    """UI mask for typical BlueStacks 1080×1920 KingShot portrait."""
    from ks.cartograph.mask import bluestacks_mask_config as _cfg

    return _cfg()


def run_live_frames(
    frames: list,  # CapturedFrame
    *,
    mask_cfg: MaskConfig | None = None,
    mat: np.ndarray = DEFAULT_MAT,
    out_yaml: Path | None = None,
    radius: int = 30,
    step: int = 10,
) -> CartographResult:
    """OCR + project a list of live CapturedFrame objects."""
    mask_cfg = mask_cfg or bluestacks_mask_config()
    viewports: dict[str, tuple[int, int]] = {}
    for fr in frames:
        if fr.viewport is not None:
            viewports[fr.name] = fr.viewport
    if not viewports:
        raise RuntimeError("no viewport OCR on any live frame")

    cx = int(round(sum(v[0] for v in viewports.values()) / len(viewports)))
    cy = int(round(sum(v[1] for v in viewports.values()) / len(viewports)))
    plan = plan_jumps(cx, cy, radius, step)

    all_hits: list[StructureHit] = []
    for fr in frames:
        if fr.viewport is None:
            continue
        band = mask_and_crop(fr.image, mask_cfg)
        ch, cw = band.shape[:2]
        boxes = extract_labels(band)
        all_hits.extend(
            hits_from_label_boxes(
                boxes,
                viewport=fr.viewport,
                crop_center=(cw / 2.0, ch / 2.0),
                mat=mat,
                source=fr.name,
            )
        )

    merged = dedupe_hits(all_hits)
    if out_yaml is not None:
        out_yaml.parent.mkdir(parents=True, exist_ok=True)
        out_yaml.write_text(hits_to_blockers_yaml(merged), encoding="utf-8")

    return CartographResult(
        center=(cx, cy),
        radius=radius,
        plan=plan,
        hits=merged,
        out_yaml=out_yaml,
    )


def format_dry_run(plan: JumpPlan) -> str:
    lines = [
        f"center={plan.center[0]},{plan.center[1]} radius={plan.radius} step={plan.step}",
        f"jumps={len(plan.jumps)} swipe_offsets={list(plan.swipe_offsets)}",
        "jump list:",
    ]
    for x, y in plan.jumps:
        lines.append(f"  {x},{y}")
    return "\n".join(lines)
