"""Provenance-aware entity observations and catalog merging."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Callable, Sequence

import cv2
import numpy as np

from ks.cartograph.labels import infer_kind, parse_level
from ks.cartograph.landmarks import normalize_landmark_name
from ks.cartograph.models import FOOTPRINTS
from ks.cartograph.project import AffineProjection, round_tile

PROVENANCE_PRIORITY = {
    "operator": 4,
    "popup_exact": 3,
    "ocr_projected": 2,
    "visual_projected": 1,
}

_LORD_ID = re.compile(r"lord\s*(\d{4,})", re.I)


@dataclass(frozen=True)
class EntityObservation:
    """One object sighting in a single frame, optionally world-projected."""

    frame: str
    pixel_x: float
    pixel_y: float
    identity: str | None
    label: str
    kind: str
    level: int | None
    confidence: float
    provenance: str
    world_x: float | None = None
    world_y: float | None = None
    tile_x: int | None = None
    tile_y: int | None = None
    popup_path: str | None = None

    def __post_init__(self) -> None:
        if not self.frame:
            raise ValueError("frame must be non-empty")
        if self.kind not in FOOTPRINTS and self.kind != "unknown":
            raise ValueError(f"unknown kind {self.kind!r}")
        if not (0.0 < self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in (0, 1]; got {self.confidence}"
            )
        if self.provenance not in PROVENANCE_PRIORITY:
            raise ValueError(f"unsupported provenance {self.provenance!r}")
        if not math.isfinite(self.pixel_x) or not math.isfinite(self.pixel_y):
            raise ValueError("pixel coordinates must be finite")


@dataclass(frozen=True)
class EntityCatalogEntry:
    """Merged object with world coordinates and provenance metadata."""

    identity: str | None
    label: str
    kind: str
    level: int | None
    world_x: float
    world_y: float
    tile_x: int
    tile_y: int
    confidence: float
    provenance: str
    source_frames: tuple[str, ...]
    coordinate_residual_px: float | None = None
    popup_path: str | None = None
    w: int = 1
    h: int = 1


def project_observation(
    observation: EntityObservation,
    *,
    projection: AffineProjection,
    frame_offset: tuple[float, float],
    crop_center: tuple[float, float],
) -> EntityObservation:
    """Project a band-local pixel observation into world coordinates."""
    panorama_x = (
        projection.pixel_origin[0]
        + frame_offset[0]
        + (observation.pixel_x - crop_center[0])
    )
    panorama_y = (
        projection.pixel_origin[1]
        + frame_offset[1]
        + (observation.pixel_y - crop_center[1])
    )
    world_x, world_y = projection.world_from_pixel(panorama_x, panorama_y)
    tile_x, tile_y = round_tile(world_x, world_y)
    return replace(
        observation,
        world_x=float(world_x),
        world_y=float(world_y),
        tile_x=tile_x,
        tile_y=tile_y,
    )


def detect_frame_observations(
    band: np.ndarray,
    *,
    frame: str,
    labels_with_confidence: Sequence[tuple[str, float, float, float]] | None = None,
    sprite_matcher: Callable[..., list[EntityObservation]] | None = None,
) -> list[EntityObservation]:
    """Detect OCR and conservative visual object candidates in one band."""
    if band.ndim != 3 or band.shape[2] != 3:
        raise ValueError(f"band must be HxWx3; got {band.shape}")
    if band.shape[0] < 32 or band.shape[1] < 32:
        raise ValueError(f"band too small for detection; got {band.shape}")

    observations: list[EntityObservation] = []
    labeled_centers: list[tuple[float, float]] = []
    for label, px, py, conf in labels_with_confidence or ():
        kind = infer_kind(label) or "unknown"
        identity = normalize_landmark_name(label)
        if identity is None and kind == "city":
            if m := _LORD_ID.search(label):
                identity = f"lord{m.group(1)}"
        observations.append(
            EntityObservation(
                frame=frame,
                pixel_x=float(px),
                pixel_y=float(py),
                identity=identity,
                label=str(label).strip(),
                kind=kind,
                level=parse_level(label),
                confidence=float(min(1.0, max(1e-3, conf))),
                provenance="ocr_projected",
            )
        )
        labeled_centers.append((float(px), float(py)))

    matcher = sprite_matcher
    if matcher is None:
        try:
            from ks.cartograph.sprites import match_sprite_observations

            matcher = match_sprite_observations
        except ImportError:
            matcher = None
    if matcher is not None:
        for sprite in matcher(band, frame=frame):
            if any(
                (sprite.pixel_x - lx) ** 2 + (sprite.pixel_y - ly) ** 2 < 45**2
                for lx, ly in labeled_centers
            ):
                continue
            observations.append(sprite)
            labeled_centers.append((sprite.pixel_x, sprite.pixel_y))

    for px, py, conf in _badge_candidates(band):
        if any((px - lx) ** 2 + (py - ly) ** 2 < 45**2 for lx, ly in labeled_centers):
            continue
        observations.append(
            EntityObservation(
                frame=frame,
                pixel_x=px,
                pixel_y=py,
                identity=None,
                label="",
                kind="unknown",
                level=None,
                confidence=conf,
                provenance="visual_projected",
            )
        )
    return observations


def merge_entity_observations(
    observations: Sequence[EntityObservation],
    *,
    max_world_delta: float = 0.75,
    matrix: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> list[EntityCatalogEntry]:
    """Merge cross-frame observations by identity/proximity with provenance priority."""
    if max_world_delta <= 0:
        raise ValueError(f"max_world_delta must be positive; got {max_world_delta}")
    projected = [item for item in observations if item.world_x is not None]
    if len(projected) != len(observations):
        raise ValueError("all observations must be world-projected before merge")

    groups: list[list[EntityObservation]] = []
    for item in projected:
        placed = False
        for group in groups:
            if _same_entity(group[0], item, max_world_delta=max_world_delta):
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    catalog: list[EntityCatalogEntry] = []
    for group in groups:
        catalog.append(_catalog_entry_from_group(group, matrix=matrix))
    return catalog


def _same_entity(
    left: EntityObservation,
    right: EntityObservation,
    *,
    max_world_delta: float,
) -> bool:
    assert left.world_x is not None and left.world_y is not None
    assert right.world_x is not None and right.world_y is not None
    distance = math.hypot(left.world_x - right.world_x, left.world_y - right.world_y)
    if left.identity and right.identity:
        if left.identity == right.identity:
            if distance > max_world_delta:
                raise ValueError(
                    f"coordinate disagreement for {left.identity}: "
                    f"{distance:.3f} world units exceeds {max_world_delta}"
                )
            return True
        return False
    # Named OCR/popup can absorb nearby unlabeled visual candidates.
    if bool(left.identity) != bool(right.identity):
        return distance <= max_world_delta
    if left.kind != right.kind and "unknown" not in {left.kind, right.kind}:
        return False
    return distance <= max_world_delta


def _catalog_entry_from_group(
    group: Sequence[EntityObservation],
    *,
    matrix: tuple[tuple[float, float], tuple[float, float]] | None,
) -> EntityCatalogEntry:
    ranked = sorted(
        group,
        key=lambda item: (
            PROVENANCE_PRIORITY[item.provenance],
            item.confidence,
        ),
        reverse=True,
    )
    primary = ranked[0]
    assert primary.world_x is not None and primary.world_y is not None
    assert primary.tile_x is not None and primary.tile_y is not None
    footprint = FOOTPRINTS.get(primary.kind, (1, 1))
    residual = _coordinate_residual_px(group, primary, matrix=matrix)
    label = next((item.label for item in ranked if item.label), primary.label)
    identity = next((item.identity for item in ranked if item.identity), None)
    level = next((item.level for item in ranked if item.level is not None), None)
    popup_path = next((item.popup_path for item in ranked if item.popup_path), None)
    return EntityCatalogEntry(
        identity=identity,
        label=label,
        kind=primary.kind,
        level=level,
        world_x=float(primary.world_x),
        world_y=float(primary.world_y),
        tile_x=int(primary.tile_x),
        tile_y=int(primary.tile_y),
        confidence=float(primary.confidence),
        provenance=primary.provenance,
        source_frames=tuple(sorted({item.frame for item in group})),
        coordinate_residual_px=residual,
        popup_path=popup_path,
        w=footprint[0],
        h=footprint[1],
    )


def _coordinate_residual_px(
    group: Sequence[EntityObservation],
    primary: EntityObservation,
    *,
    matrix: tuple[tuple[float, float], tuple[float, float]] | None,
) -> float:
    assert primary.world_x is not None and primary.world_y is not None
    if len(group) < 2:
        return 0.0
    residuals = []
    for item in group:
        assert item.world_x is not None and item.world_y is not None
        world_delta = np.asarray(
            [item.world_x - primary.world_x, item.world_y - primary.world_y],
            dtype=float,
        )
        if matrix is None:
            residuals.append(float(np.linalg.norm(world_delta)))
        else:
            residuals.append(float(np.linalg.norm(np.asarray(matrix, dtype=float) @ world_delta)))
    return float(max(residuals))


def _badge_candidates(band: np.ndarray) -> list[tuple[float, float, float]]:
    """Find red circular level badges associated with nearby structure."""
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    red_a = cv2.inRange(hsv, np.array([0, 55, 70]), np.array([18, 255, 255]))
    red_b = cv2.inRange(hsv, np.array([160, 55, 70]), np.array([179, 255, 255]))
    raw_mask = cv2.bitwise_or(red_a, red_b)
    mask = cv2.medianBlur(raw_mask, 3)
    height, width = band.shape[:2]
    grass = cv2.inRange(hsv, np.array([25, 35, 35]), np.array([95, 255, 255])) > 0
    out: list[tuple[float, float, float]] = []

    circles = cv2.HoughCircles(
        mask,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=28,
        param1=70,
        param2=8,
        minRadius=7,
        maxRadius=22,
    )
    if circles is not None:
        for x, y, radius in circles[0]:
            candidate = _badge_object_center(
                float(x),
                float(y),
                float(radius),
                grass=grass,
                width=width,
                height=height,
            )
            if candidate is not None:
                out.append(candidate)
        if out:
            return out

    contours, _ = cv2.findContours(
        raw_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < 40 or area > 900:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        circularity = area / (math.pi * radius * radius + 1e-6)
        if circularity < 0.45:
            continue
        candidate = _badge_object_center(
            float(cx),
            float(cy),
            float(radius),
            grass=grass,
            width=width,
            height=height,
            confidence=0.45,
        )
        if candidate is not None:
            out.append(candidate)
    return out


def _badge_object_center(
    cx: float,
    cy: float,
    radius: float,
    *,
    grass: np.ndarray,
    width: int,
    height: int,
    confidence: float | None = None,
) -> tuple[float, float, float] | None:
    if not (7 <= radius <= 22):
        return None
    if not (16 <= cx <= width - 16 and 16 <= cy <= height - 16):
        return None
    y0 = int(max(0, cy + 0.5 * radius))
    y1 = int(min(height, cy + 4.0 * radius))
    x0 = int(max(0, cx - 2.5 * radius))
    x1 = int(min(width, cx + 2.5 * radius))
    body = grass[y0:y1, x0:x1]
    if body.size == 0:
        return None
    # Require a non-grass body under the badge so pure HUD red is ignored.
    if float((~body).mean()) < 0.08:
        return None
    score = float(confidence if confidence is not None else min(0.75, 0.35 + 0.02 * radius))
    return (cx, cy + 1.4 * radius, score)
