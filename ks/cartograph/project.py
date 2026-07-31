"""Pixel ↔ world projection for cartograph samples."""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Integral
from typing import Sequence

import numpy as np

Matrix2x2 = tuple[tuple[float, float], tuple[float, float]]
MAX_MATRIX_CONDITION_NUMBER = 1e12


def _validated_pair(values: Sequence[float], *, name: str) -> tuple[float, float]:
    try:
        pair = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must contain exactly two numeric values") from None
    if pair.shape != (2,):
        raise ValueError(f"{name} must contain exactly two values; got shape {pair.shape}")
    if not np.isfinite(pair).all():
        raise ValueError(f"{name} must contain finite values")
    return float(pair[0]), float(pair[1])


def _immutable_matrix(matrix: np.ndarray) -> Matrix2x2:
    return (
        (float(matrix[0, 0]), float(matrix[0, 1])),
        (float(matrix[1, 0]), float(matrix[1, 1])),
    )


def _validated_matrix(matrix: np.ndarray) -> tuple[Matrix2x2, Matrix2x2]:
    try:
        validated = np.asarray(matrix, dtype=float)
    except (TypeError, ValueError):
        raise ValueError("matrix must contain numeric values") from None
    if validated.shape != (2, 2):
        raise ValueError(f"matrix must have shape (2, 2); got {validated.shape}")
    if not np.isfinite(validated).all():
        raise ValueError("matrix must contain finite values")
    try:
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            inverse = np.linalg.inv(validated)
    except np.linalg.LinAlgError:
        raise ValueError("matrix must be invertible") from None
    if not np.isfinite(inverse).all():
        raise ValueError("matrix inverse must contain finite values")
    if np.linalg.cond(validated) > MAX_MATRIX_CONDITION_NUMBER:
        raise ValueError("matrix must be numerically stable")

    return _immutable_matrix(validated), _immutable_matrix(inverse)


def _transform(
    matrix: Matrix2x2, vector_x: float, vector_y: float
) -> tuple[float, float]:
    return (
        matrix[0][0] * vector_x + matrix[0][1] * vector_y,
        matrix[1][0] * vector_x + matrix[1][1] * vector_y,
    )


@dataclass(frozen=True)
class AffineProjection:
    """Validated affine mapping between world tiles and image pixels."""

    center: tuple[float, float]
    pixel_origin: tuple[float, float]
    matrix: Matrix2x2
    _inverse_matrix: Matrix2x2 = field(
        init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        center = _validated_pair(self.center, name="center")
        pixel_origin = _validated_pair(self.pixel_origin, name="pixel_origin")
        matrix, inverse_matrix = _validated_matrix(self.matrix)
        object.__setattr__(self, "center", center)
        object.__setattr__(self, "pixel_origin", pixel_origin)
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "_inverse_matrix", inverse_matrix)

    def pixel_from_world(self, wx: float, wy: float) -> tuple[float, float]:
        pixel_delta_x, pixel_delta_y = _transform(
            self.matrix,
            wx - self.center[0],
            wy - self.center[1],
        )
        return (
            self.pixel_origin[0] + pixel_delta_x,
            self.pixel_origin[1] + pixel_delta_y,
        )

    def world_from_pixel(self, px: float, py: float) -> tuple[float, float]:
        world_delta_x, world_delta_y = _transform(
            self._inverse_matrix,
            px - self.pixel_origin[0],
            py - self.pixel_origin[1],
        )
        return (
            self.center[0] + world_delta_x,
            self.center[1] + world_delta_y,
        )

    def tile_polygon(
        self, world_x: float, world_y: float
    ) -> tuple[tuple[float, float], ...]:
        world_corners = (
            (world_x - 0.5, world_y - 0.5),
            (world_x + 0.5, world_y - 0.5),
            (world_x + 0.5, world_y + 0.5),
            (world_x - 0.5, world_y + 0.5),
        )
        return tuple(self.pixel_from_world(*corner) for corner in world_corners)

    def world_bounds_for_image(
        self, width: int, height: int
    ) -> tuple[float, float, float, float]:
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, Integral)
            or not isinstance(height, Integral)
            or width <= 0
            or height <= 0
        ):
            raise ValueError(
                "image dimensions must be positive integers; "
                f"got width={width!r}, height={height!r}"
            )

        pixel_corners = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
        world_corners = tuple(
            self.world_from_pixel(*corner) for corner in pixel_corners
        )
        world_x_values, world_y_values = zip(*world_corners, strict=True)
        return (
            min(world_x_values),
            min(world_y_values),
            max(world_x_values),
            max(world_y_values),
        )


def world_from_pixel(
    px: float,
    py: float,
    *,
    viewport: tuple[float, float],
    crop_center: tuple[float, float],
    mat: np.ndarray,
) -> tuple[float, float]:
    """Map a pixel in the (cropped) frame to world tiles.

    ``crop_center`` is the pixel that corresponds to ``viewport`` (usually
    the geometric center of the cropped map band).
    ``mat`` is 2×2 such that ``pixel_delta = mat @ world_delta``.
    """
    m = np.asarray(mat, dtype=float)
    assert m.shape == (2, 2), m.shape
    pixel_delta = np.array([px - crop_center[0], py - crop_center[1]], dtype=float)
    world_delta = np.linalg.inv(m) @ pixel_delta
    return float(viewport[0] + world_delta[0]), float(viewport[1] + world_delta[1])


def pixel_from_world(
    wx: float,
    wy: float,
    *,
    viewport: tuple[float, float],
    crop_center: tuple[float, float],
    mat: np.ndarray,
) -> tuple[float, float]:
    m = np.asarray(mat, dtype=float)
    assert m.shape == (2, 2), m.shape
    world_delta = np.array([wx - viewport[0], wy - viewport[1]], dtype=float)
    pixel_delta = m @ world_delta
    return float(crop_center[0] + pixel_delta[0]), float(crop_center[1] + pixel_delta[1])


def round_tile(wx: float, wy: float) -> tuple[int, int]:
    return int(round(wx)), int(round(wy))
