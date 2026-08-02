"""Robust world-to-pixel calibration from clicked map objects."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class CalibrationObservation:
    frame: str
    world_x: float
    world_y: float
    pixel_x: float
    pixel_y: float
    weight: float = 1.0


@dataclass(frozen=True)
class AffineCalibration:
    matrix: np.ndarray
    accepted: tuple[CalibrationObservation, ...]
    rejected: tuple[CalibrationObservation, ...]


@dataclass(frozen=True)
class FrameOffsetCalibration:
    matrix: np.ndarray
    frame_offsets: dict[str, tuple[float, float]]
    residual_rms_px: float


@dataclass(frozen=True)
class ScaleFromTwoPoints:
    """Scale along the chord between two measured (world, pixel) points.

    Use this to validate screenshot scale from time to time: pick two known
    world anchors visible in pixel space, measure their separation, divide.
    One chord gives px/tile along that direction; for diamond geometry you
    need two independent chords (e.g. mostly-X and mostly-Y).
    """

    label_a: str
    label_b: str
    world_a: tuple[float, float]
    world_b: tuple[float, float]
    pixel_a: tuple[float, float]
    pixel_b: tuple[float, float]
    world_delta: tuple[float, float]
    pixel_delta: tuple[float, float]
    world_length_tiles: float
    pixel_length_px: float
    px_per_tile: float


@dataclass(frozen=True)
class ScaleValidation:
    """Two independent two-point chords used as the scale check."""

    chord_a: ScaleFromTwoPoints
    chord_b: ScaleFromTwoPoints
    ok: bool
    detail: str


def sample_indices_for_scale_checks(
    n: int,
    *,
    fraction: float = 0.2,
    min_samples: int = 2,
    max_samples: int = 12,
) -> list[int]:
    """Pick a spread of indices for periodic scale checks (default ~20%).

    Always aims for at least ``min_samples`` and at most ``max_samples``
    (besides a fixed reference, which the caller holds separately).
    """
    if n < 0:
        raise ValueError(f"n must be non-negative; got {n}")
    if not (0.0 < fraction <= 1.0):
        raise ValueError(f"fraction must be in (0, 1]; got {fraction}")
    if min_samples < 1:
        raise ValueError(f"min_samples must be >= 1; got {min_samples}")
    if max_samples < min_samples:
        raise ValueError("max_samples must be >= min_samples")
    if n == 0:
        return []
    target = int(round(n * fraction))
    target = max(min_samples, min(max_samples, max(target, min_samples)))
    target = min(target, n)
    if target == n:
        return list(range(n))
    if target == 1:
        return [n // 2]
    # Evenly spaced through the list so 10–30% still covers the grid.
    return sorted({int(round(i * (n - 1) / (target - 1))) for i in range(target)})


def measure_scale_from_observations_on_frame(
    observations: Sequence[CalibrationObservation],
) -> ScaleFromTwoPoints:
    """Two-point scale from two known anchors on the *same* screenshot."""
    if len(observations) < 2:
        raise ValueError("need at least two observations on one screenshot")
    frames = {item.frame for item in observations}
    if len(frames) != 1:
        raise ValueError(
            "same-screenshot scale check requires one frame; "
            f"got {sorted(frames)}"
        )
    # Farthest pair in world space → most stable px/tile.
    best: ScaleFromTwoPoints | None = None
    for a, b in combinations(observations, 2):
        seg = measure_scale_from_two_points(
            label_a=f"{a.frame}:{a.world_x:g},{a.world_y:g}",
            world_a=(a.world_x, a.world_y),
            pixel_a=(a.pixel_x, a.pixel_y),
            label_b=f"{b.frame}:{b.world_x:g},{b.world_y:g}",
            world_b=(b.world_x, b.world_y),
            pixel_b=(b.pixel_x, b.pixel_y),
        )
        if best is None or seg.world_length_tiles > best.world_length_tiles:
            best = seg
    assert best is not None
    return best


def measure_scale_from_two_points(
    *,
    label_a: str,
    world_a: tuple[float, float],
    pixel_a: tuple[float, float],
    label_b: str,
    world_b: tuple[float, float],
    pixel_b: tuple[float, float],
) -> ScaleFromTwoPoints:
    """Measure px/tile from exactly two known points (one baseline)."""
    wa = np.asarray(world_a, dtype=float)
    wb = np.asarray(world_b, dtype=float)
    pa = np.asarray(pixel_a, dtype=float)
    pb = np.asarray(pixel_b, dtype=float)
    if wa.shape != (2,) or wb.shape != (2,) or pa.shape != (2,) or pb.shape != (2,):
        raise ValueError("world/pixel points must be length-2")
    world_delta = wb - wa
    pixel_delta = pb - pa
    world_len = float(np.linalg.norm(world_delta))
    pixel_len = float(np.linalg.norm(pixel_delta))
    if world_len < 1e-6:
        raise ValueError(
            f"two-point scale needs distinct world coords; got {world_a} and {world_b}"
        )
    if pixel_len < 1e-6:
        raise ValueError(
            f"two-point scale needs distinct pixel coords; got {pixel_a} and {pixel_b}"
        )
    return ScaleFromTwoPoints(
        label_a=label_a,
        label_b=label_b,
        world_a=(float(wa[0]), float(wa[1])),
        world_b=(float(wb[0]), float(wb[1])),
        pixel_a=(float(pa[0]), float(pa[1])),
        pixel_b=(float(pb[0]), float(pb[1])),
        world_delta=(float(world_delta[0]), float(world_delta[1])),
        pixel_delta=(float(pixel_delta[0]), float(pixel_delta[1])),
        world_length_tiles=world_len,
        pixel_length_px=pixel_len,
        px_per_tile=pixel_len / world_len,
    )


def validate_scale_from_two_chords(
    chord_a: ScaleFromTwoPoints,
    chord_b: ScaleFromTwoPoints,
    *,
    min_world_separation: float = 2.0,
    max_relative_disagreement: float = 0.35,
) -> ScaleValidation:
    """Validate screenshot scale with two independent two-point measurements.

    Call this from time to time (capture / restitch): each chord is two known
    world points with independently measured pixel positions. Checks that both
    chords are long enough, not parallel in world space, and that their
    px/tile estimates agree within ``max_relative_disagreement``.
    """
    if min_world_separation <= 0:
        raise ValueError(
            f"min_world_separation must be positive; got {min_world_separation}"
        )
    if not (0.0 < max_relative_disagreement < 1.0):
        raise ValueError(
            "max_relative_disagreement must be in (0, 1); "
            f"got {max_relative_disagreement}"
        )
    if chord_a.world_length_tiles < min_world_separation:
        return ScaleValidation(
            chord_a=chord_a,
            chord_b=chord_b,
            ok=False,
            detail=(
                f"chord A world length {chord_a.world_length_tiles:.2f} "
                f"< {min_world_separation}"
            ),
        )
    if chord_b.world_length_tiles < min_world_separation:
        return ScaleValidation(
            chord_a=chord_a,
            chord_b=chord_b,
            ok=False,
            detail=(
                f"chord B world length {chord_b.world_length_tiles:.2f} "
                f"< {min_world_separation}"
            ),
        )
    # Chords should not be nearly parallel in world space (need 2 axes).
    wa = np.asarray(chord_a.world_delta, dtype=float)
    wb = np.asarray(chord_b.world_delta, dtype=float)
    cross = abs(float(wa[0] * wb[1] - wa[1] * wb[0]))
    if cross < 1e-3 * (chord_a.world_length_tiles * chord_b.world_length_tiles):
        return ScaleValidation(
            chord_a=chord_a,
            chord_b=chord_b,
            ok=False,
            detail="two scale chords are nearly parallel; need independent axes",
        )
    mean_scale = 0.5 * (chord_a.px_per_tile + chord_b.px_per_tile)
    if mean_scale <= 0:
        return ScaleValidation(
            chord_a=chord_a,
            chord_b=chord_b,
            ok=False,
            detail="non-positive mean px/tile",
        )
    rel = abs(chord_a.px_per_tile - chord_b.px_per_tile) / mean_scale
    if rel > max_relative_disagreement:
        return ScaleValidation(
            chord_a=chord_a,
            chord_b=chord_b,
            ok=False,
            detail=(
                f"px/tile disagreement {rel:.0%} exceeds "
                f"{max_relative_disagreement:.0%} "
                f"({chord_a.px_per_tile:.1f} vs {chord_b.px_per_tile:.1f})"
            ),
        )
    return ScaleValidation(
        chord_a=chord_a,
        chord_b=chord_b,
        ok=True,
        detail=(
            f"ok: {chord_a.px_per_tile:.1f} and {chord_b.px_per_tile:.1f} px/tile "
            f"(relΔ={rel:.0%})"
        ),
    )


def _design_matrix(
    observations: Sequence[CalibrationObservation],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    design = np.array(
        [[item.world_x, item.world_y, 1.0] for item in observations],
        dtype=float,
    )
    pixels = np.array(
        [[item.pixel_x, item.pixel_y] for item in observations],
        dtype=float,
    )
    weights = np.array([item.weight for item in observations], dtype=float)
    return design, pixels, weights


def _fit(observations: Sequence[CalibrationObservation]) -> np.ndarray:
    design, pixels, weights = _design_matrix(observations)
    weighted_design = design * np.sqrt(weights)[:, None]
    weighted_pixels = pixels * np.sqrt(weights)[:, None]
    coefficients, _, rank, _ = np.linalg.lstsq(
        weighted_design,
        weighted_pixels,
        rcond=None,
    )
    if rank < 3:
        raise ValueError("calibration observations must span both world axes")
    return coefficients.T


def _residuals(
    observations: Sequence[CalibrationObservation],
    matrix: np.ndarray,
) -> np.ndarray:
    design, pixels, _ = _design_matrix(observations)
    predicted = design @ matrix.T
    return np.linalg.norm(predicted - pixels, axis=1)


def fit_world_to_pixel(
    observations: Sequence[CalibrationObservation],
    residual_limit_px: float = 35.0,
) -> AffineCalibration:
    """Fit a 2×3 affine transform and reject inconsistent OCR observations."""
    if residual_limit_px <= 0:
        raise ValueError(
            f"residual_limit_px must be positive; got {residual_limit_px}"
        )
    if len(observations) < 3:
        raise ValueError("at least three calibration observations are required")
    if any(item.weight <= 0 for item in observations):
        raise ValueError("calibration observation weights must be positive")

    candidates: list[tuple[int, float, float, np.ndarray, np.ndarray]] = []
    for sample_indexes in combinations(range(len(observations)), 3):
        sample = [observations[index] for index in sample_indexes]
        try:
            matrix = _fit(sample)
        except ValueError:
            continue
        residuals = _residuals(observations, matrix)
        inliers = residuals <= residual_limit_px
        support = float(
            sum(item.weight for item, keep in zip(observations, inliers) if keep)
        )
        error = float(residuals[inliers].mean()) if bool(inliers.any()) else np.inf
        candidates.append((int(inliers.sum()), support, -error, matrix, inliers))

    if not candidates:
        raise ValueError("calibration observations must span both world axes")
    _, _, _, _, inliers = max(candidates, key=lambda item: item[:3])
    accepted = tuple(
        item for item, keep in zip(observations, inliers, strict=True) if keep
    )
    rejected = tuple(
        item for item, keep in zip(observations, inliers, strict=True) if not keep
    )
    matrix = _fit(accepted)
    return AffineCalibration(matrix=matrix, accepted=accepted, rejected=rejected)


def fit_frame_offsets(
    observations: Sequence[CalibrationObservation],
    *,
    reference_frame: str,
    residual_limit_px: float = 20.0,
) -> FrameOffsetCalibration:
    """Fit shared world scale plus one image-space offset per captured frame."""
    if len(observations) < 5:
        raise ValueError("at least five exact-object observations are required")
    frames = sorted({item.frame for item in observations})
    if reference_frame not in frames:
        raise ValueError(f"reference frame {reference_frame!r} has no observations")
    world = np.array(
        [[item.world_x, item.world_y] for item in observations],
        dtype=float,
    )
    if np.linalg.matrix_rank(world - world.mean(axis=0)) < 2:
        raise ValueError("exact objects must span both world axes")

    world_center = world.mean(axis=0)
    design = np.zeros((len(observations), 2 + len(frames)), dtype=float)
    design[:, :2] = world - world_center
    frame_index = {frame: index for index, frame in enumerate(frames)}
    for row, item in enumerate(observations):
        design[row, 2 + frame_index[item.frame]] = 1.0
    pixels = np.array(
        [[item.pixel_x, item.pixel_y] for item in observations],
        dtype=float,
    )
    coefficients, _, rank, _ = np.linalg.lstsq(design, pixels, rcond=None)
    if rank < design.shape[1]:
        raise ValueError("exact-object observations do not constrain every frame")
    predicted = design @ coefficients
    residual_rms = float(np.sqrt(np.mean(np.square(predicted - pixels))))
    if residual_rms > residual_limit_px:
        raise ValueError(
            f"exact-object residual {residual_rms:.1f}px exceeds "
            f"{residual_limit_px:.1f}px"
        )

    matrix = coefficients[:2, :].T
    biases = coefficients[2:, :]
    reference_bias = biases[frame_index[reference_frame]]
    offsets = {
        frame: (
            float(reference_bias[0] - biases[index, 0]),
            float(reference_bias[1] - biases[index, 1]),
        )
        for frame, index in frame_index.items()
    }
    return FrameOffsetCalibration(
        matrix=matrix,
        frame_offsets=offsets,
        residual_rms_px=residual_rms,
    )
