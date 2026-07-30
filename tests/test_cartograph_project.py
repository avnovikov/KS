"""Tests for cartograph pixel↔world projection."""

import numpy as np
import pytest

from ks.cartograph.project import pixel_from_world, round_tile, world_from_pixel


def test_crop_center_maps_to_viewport() -> None:
    mat = np.eye(2) * 10.0
    wx, wy = world_from_pixel(
        50,
        40,
        viewport=(698.0, 816.0),
        crop_center=(50.0, 40.0),
        mat=mat,
    )
    assert wx == pytest.approx(698.0)
    assert wy == pytest.approx(816.0)


def test_round_trip() -> None:
    mat = np.array([[95.7, -99.5], [-67.7, -68.1]], dtype=float)
    vp = (700.0, 820.0)
    cc = (540.0, 833.0)
    px, py = pixel_from_world(705, 823, viewport=vp, crop_center=cc, mat=mat)
    wx, wy = world_from_pixel(px, py, viewport=vp, crop_center=cc, mat=mat)
    assert wx == pytest.approx(705.0, abs=1e-6)
    assert wy == pytest.approx(823.0, abs=1e-6)


def test_round_tile() -> None:
    assert round_tile(698.4, 815.6) == (698, 816)
