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
