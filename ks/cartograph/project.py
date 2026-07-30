"""Pixel ↔ world projection for cartograph samples."""

from __future__ import annotations

import numpy as np


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
