"""Cartograph orchestration: dry-run, fixture, and live entry points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import yaml

from ks.cartograph.dedupe import dedupe_hits
from ks.cartograph.entities import (
    EntityCatalogEntry,
    EntityObservation,
    detect_frame_observations,
    merge_entity_observations,
    project_observation,
)
from ks.cartograph.labels import extract_labels, hits_from_label_boxes
from ks.cartograph.landmarks import extract_name_landmarks
from ks.cartograph.live_capture import CapturedFrame
from ks.cartograph.mask import MaskConfig, mask_and_crop
from ks.cartograph.models import StructureHit
from ks.cartograph.mosaic import MosaicResult, mosaic_projection, stitch_grid_lattice
from ks.cartograph.project import Matrix2x2
from ks.cartograph.registration import (
    STATIC_RESIDUAL_LIMIT_PX,
    CompetingFeatureTrackError,
    GlobalRegistration,
    build_registration_constraints,
    competing_feature_track_pairs,
    solve_frame_translations,
)
from ks.cartograph.render_map import (
    MapEntity,
    registration_document,
    write_map_bundle,
    _digital_tile_records,
)
from ks.cartograph.h3_index import default_crs_for_center
from ks.cartograph.store import write_capture_db
from ks.cartograph.sweep import JumpPlan, plan_jumps


# Default MAT from bear-trap stitch×viewport fit (FINDINGS / ocr-calibration).
DEFAULT_MAT = np.array(
    [[95.70840124, -99.49624005], [-67.69089597, -68.09304851]],
    dtype=float,
)

DEFAULT_SEED_CALIBRATION_NAME = "exact-coordinate-calibration-v3.yaml"
REFERENCE_FRAME = "c0_center"


@dataclass(frozen=True)
class CartographResult:
    center: tuple[int, int]
    radius: int
    plan: JumpPlan
    hits: list[StructureHit]
    out_yaml: Path | None = None


@dataclass(frozen=True)
class SeedCalibration:
    """Exact clicked world authority used to seed translation registration."""

    path: Path
    reference_frame: str
    matrix: Matrix2x2
    frame_offsets: Mapping[str, tuple[float, float]]
    center: tuple[int, int]


@dataclass(frozen=True)
class DigitizedCaptureResult:
    """Registered mosaic plus provenance-aware entity catalog."""

    center: tuple[int, int]
    kingdom: str
    mosaic: MosaicResult
    registration: GlobalRegistration
    catalog: list[EntityCatalogEntry]
    entities: list[MapEntity]
    out_dir: Path


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
    vp = raw.get("viewport") or raw.get("viewports") or raw
    out: dict[str, tuple[int, int]] = {}
    for key, val in vp.items():
        if not isinstance(val, (dict, list, tuple)):
            continue
        name = Path(str(key)).stem
        if isinstance(val, dict):
            out[name] = (int(val["x"]), int(val["y"]))
        else:
            if len(val) != 2:
                raise ValueError(f"viewport {name!r} must be [x, y]; got {val!r}")
            out[name] = (int(val[0]), int(val[1]))
    return out


def load_seed_calibration(path: Path) -> SeedCalibration:
    """Load exact clicked matrix + seed frame offsets from YAML."""
    if not path.is_file():
        raise FileNotFoundError(f"seed calibration not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"seed calibration must be a mapping; got {type(raw).__name__}")

    reference = str(raw.get("reference_frame") or REFERENCE_FRAME)
    matrix_raw = raw.get("matrix")
    offsets_raw = raw.get("frame_offsets")
    if matrix_raw is None or offsets_raw is None:
        raise ValueError("seed calibration requires matrix and frame_offsets")

    matrix_arr = np.asarray(matrix_raw, dtype=float)
    if matrix_arr.shape != (2, 2):
        raise ValueError(
            f"seed matrix must be 2x2; got shape {matrix_arr.shape}"
        )
    if not np.isfinite(matrix_arr).all():
        raise ValueError("seed matrix must contain finite values")
    matrix: Matrix2x2 = (
        (float(matrix_arr[0, 0]), float(matrix_arr[0, 1])),
        (float(matrix_arr[1, 0]), float(matrix_arr[1, 1])),
    )

    if not isinstance(offsets_raw, dict) or not offsets_raw:
        raise ValueError("frame_offsets must be a non-empty mapping")
    frame_offsets: dict[str, tuple[float, float]] = {}
    for name, offset in offsets_raw.items():
        values = np.asarray(offset, dtype=float)
        if values.shape != (2,) or not np.isfinite(values).all():
            raise ValueError(f"frame offset for {name!r} must be two finite values")
        frame_offsets[str(name)] = (float(values[0]), float(values[1]))
    if reference not in frame_offsets:
        raise ValueError(
            f"reference_frame {reference!r} missing from frame_offsets"
        )
    if frame_offsets[reference] != (0.0, 0.0):
        raise ValueError(
            f"reference_frame offset must be (0, 0); got {frame_offsets[reference]}"
        )

    center = _center_from_seed_document(raw, reference=reference)
    return SeedCalibration(
        path=path,
        reference_frame=reference,
        matrix=matrix,
        frame_offsets=frame_offsets,
        center=center,
    )


def _center_from_seed_document(
    raw: dict,
    *,
    reference: str,
) -> tuple[int, int]:
    observations = raw.get("observations") or {}
    if isinstance(observations, dict) and reference in observations:
        world = observations[reference].get("world")
        if world is not None and len(world) == 2:
            return int(world[0]), int(world[1])
    center_raw = raw.get("center")
    if isinstance(center_raw, dict):
        return int(center_raw["x"]), int(center_raw["y"])
    if isinstance(center_raw, (list, tuple)) and len(center_raw) == 2:
        return int(center_raw[0]), int(center_raw[1])
    raise ValueError(
        f"seed calibration missing world center for reference {reference!r}"
    )


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


def register_and_digitize_capture(
    capture_dir: Path,
    *,
    seed_calibration_path: Path | None = None,
    kingdom: str = "2379",
    out_dir: Path | None = None,
    mask_cfg: MaskConfig | None = None,
) -> DigitizedCaptureResult:
    """Register grid frames, stitch with corrected offsets, and export the catalog.

    Exact clicked seed offsets define world authority. Image matching may refine
    translations only. Canonical outputs fail closed when registration thresholds
    fail.
    """
    if not capture_dir.is_dir():
        raise FileNotFoundError(f"capture_dir not found: {capture_dir}")
    destination = out_dir or capture_dir
    destination.mkdir(parents=True, exist_ok=True)

    seed_path = seed_calibration_path or (
        capture_dir / DEFAULT_SEED_CALIBRATION_NAME
    )
    seed = load_seed_calibration(seed_path)
    mask = mask_cfg or _mask_for_capture(capture_dir)
    center = _resolve_capture_center(capture_dir, seed)
    frames = _load_grid_frames(capture_dir, expected=set(seed.frame_offsets))
    named = {frame.name: frame for frame in frames}
    if set(named) != set(seed.frame_offsets):
        missing = sorted(set(seed.frame_offsets) - set(named))
        extra = sorted(set(named) - set(seed.frame_offsets))
        raise ValueError(
            f"capture frames must match seed offsets; missing={missing}, extra={extra}"
        )

    landmarks_by_frame = {
        name: extract_name_landmarks(mask_and_crop(frame.image, mask))
        for name, frame in named.items()
    }
    constraints = build_registration_constraints(
        named,
        seed.frame_offsets,
        landmarks_by_frame,
        mask_cfg=mask,
    )
    registration = solve_frame_translations(
        constraints,
        reference_frame=seed.reference_frame,
        expected_frames=tuple(sorted(seed.frame_offsets)),
    )
    _assert_no_competing_feature_tracks(
        named,
        registration.frame_offsets,
        mask_cfg=mask,
        diagnostic_path=destination / "registration-competing-tracks.yaml",
    )

    mosaic = stitch_grid_lattice(
        frames,
        destination / "panorama.png",
        mask_cfg=mask,
        frame_offsets=dict(registration.frame_offsets),
        world_to_pixel_matrix=seed.matrix,
    )
    # Keep the operator-selected world center even if a frame viewport differs.
    if mosaic.center != center:
        mosaic = MosaicResult(
            image=mosaic.image,
            path=mosaic.path,
            center=center,
            scale_x=mosaic.scale_x,
            scale_y=mosaic.scale_y,
            origin_x=mosaic.origin_x,
            origin_y=mosaic.origin_y,
            band_w=mosaic.band_w,
            band_h=mosaic.band_h,
            world_to_pixel_matrix=mosaic.world_to_pixel_matrix,
        )

    catalog = _digitize_entities(
        named,
        registration=registration,
        mosaic=mosaic,
        mask_cfg=mask,
    )
    entities = [MapEntity.from_catalog_entry(entry) for entry in catalog]
    write_map_bundle(
        destination,
        entities,
        center=center,
        kingdom=kingdom,
        mosaic=mosaic,
        registration=registration,
    )
    _write_entities_yaml(destination / "entities.yaml", entities, center=center, kingdom=kingdom)
    _write_registration_yaml(
        destination / "registration.yaml",
        registration,
        matrix=seed.matrix,
    )
    crs = default_crs_for_center(center[0], center[1], kingdom=kingdom)
    write_capture_db(
        destination / "cartograph.sqlite",
        kingdom=kingdom,
        center=center,
        matrix=seed.matrix,
        crs=crs,
        tiles=_digital_tile_records(mosaic),
        entities=entities,
        panorama_size=(int(mosaic.image.shape[1]), int(mosaic.image.shape[0])),
        registration=registration_document(registration, matrix=seed.matrix),
    )

    return DigitizedCaptureResult(
        center=center,
        kingdom=kingdom,
        mosaic=mosaic,
        registration=registration,
        catalog=catalog,
        entities=entities,
        out_dir=destination,
    )


def _assert_no_competing_feature_tracks(
    frames: Mapping[str, CapturedFrame],
    frame_offsets: Mapping[str, tuple[float, float]],
    *,
    mask_cfg: MaskConfig,
    diagnostic_path: Path,
) -> None:
    """Fail closed when a second strong translation peak remains after fit."""
    competing = competing_feature_track_pairs(
        frames,
        frame_offsets,
        mask_cfg=mask_cfg,
    )
    if not competing:
        return
    payload = {
        "competing_feature_track_pairs": [
            {
                "frame_a": frame_a,
                "frame_b": frame_b,
                "separation_px": separation,
                "secondary_inliers": inliers,
            }
            for frame_a, frame_b, separation, inliers in competing
        ]
    }
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    details = ", ".join(
        f"{frame_a}/{frame_b} sep={separation:.2f}px inliers={inliers}"
        for frame_a, frame_b, separation, inliers in competing
    )
    raise CompetingFeatureTrackError(
        "competing feature-track peaks exceed "
        f"{STATIC_RESIDUAL_LIMIT_PX:g} px: {details}",
        competing_pairs=competing,
    )


def _mask_for_capture(capture_dir: Path) -> MaskConfig:
    calibration_path = capture_dir / "calibration.yaml"
    if calibration_path.is_file():
        raw = yaml.safe_load(calibration_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict) and raw.get("mask"):
            return mask_config_from_calibration(calibration_path)
    return bluestacks_mask_config()


def _resolve_capture_center(
    capture_dir: Path,
    seed: SeedCalibration,
) -> tuple[int, int]:
    calibration_path = capture_dir / "calibration.yaml"
    if calibration_path.is_file():
        viewports = load_viewports_yaml(calibration_path)
        if REFERENCE_FRAME in viewports:
            return viewports[REFERENCE_FRAME]
        if seed.reference_frame in viewports:
            return viewports[seed.reference_frame]
    return seed.center


def _load_grid_frames(
    capture_dir: Path,
    *,
    expected: set[str],
) -> list[CapturedFrame]:
    import cv2

    frames: list[CapturedFrame] = []
    for name in sorted(expected):
        path = capture_dir / f"{name}.png"
        if not path.is_file():
            raise FileNotFoundError(f"missing capture frame: {path}")
        image = cv2.imread(str(path))
        if image is None:
            raise RuntimeError(f"failed to read capture frame: {path}")
        frames.append(
            CapturedFrame(
                name=name,
                path=path,
                viewport=None,
                viewport_raw="",
                image=image,
            )
        )
    # Attach viewports when calibration.yaml has them (needed for mosaic center).
    calibration_path = capture_dir / "calibration.yaml"
    if calibration_path.is_file():
        viewports = load_viewports_yaml(calibration_path)
        frames = [
            CapturedFrame(
                name=frame.name,
                path=frame.path,
                viewport=viewports.get(frame.name),
                viewport_raw="",
                image=frame.image,
            )
            for frame in frames
        ]
    return frames


def _labels_with_confidence(
    band: np.ndarray,
) -> list[tuple[str, float, float, float]]:
    """OCR labels with a conservative default confidence for entity detection."""
    return [(label, px, py, 0.7) for label, px, py in extract_labels(band)]


def _digitize_entities(
    named_frames: Mapping[str, CapturedFrame],
    *,
    registration: GlobalRegistration,
    mosaic: MosaicResult,
    mask_cfg: MaskConfig,
) -> list[EntityCatalogEntry]:
    projection = mosaic_projection(mosaic)
    observations: list[EntityObservation] = []
    for name, frame in named_frames.items():
        band = mask_and_crop(frame.image, mask_cfg)
        crop_center = (band.shape[1] / 2.0, band.shape[0] / 2.0)
        offset = registration.frame_offsets[name]
        for observation in detect_frame_observations(
            band,
            frame=name,
            labels_with_confidence=_labels_with_confidence(band),
        ):
            observations.append(
                project_observation(
                    observation,
                    projection=projection,
                    frame_offset=offset,
                    crop_center=crop_center,
                )
            )
    return merge_entity_observations(
        observations,
        matrix=mosaic.world_to_pixel_matrix,
    )


def _write_entities_yaml(
    path: Path,
    entities: list[MapEntity],
    *,
    center: tuple[int, int],
    kingdom: str,
) -> None:
    payload = {
        "kingdom": kingdom,
        "center": {"x": center[0], "y": center[1]},
        "entities": [
            {
                "kind": entity.kind,
                "label": entity.label,
                "level": entity.level,
                "x": entity.x,
                "y": entity.y,
                "w": entity.w,
                "h": entity.h,
                "identity": entity.identity,
                "confidence": entity.confidence,
                "provenance": entity.provenance,
                "source_frames": list(entity.source_frames),
                "coordinate_residual_px": entity.coordinate_residual_px,
                "popup_path": entity.popup_path,
            }
            for entity in entities
        ],
    }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_registration_yaml(
    path: Path,
    registration: GlobalRegistration,
    *,
    matrix: Matrix2x2 | None = None,
) -> None:
    path.write_text(
        yaml.safe_dump(
            registration_document(registration, matrix=matrix),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
