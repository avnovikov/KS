"""Tests for viewport mosaic stitching."""

import numpy as np
import pytest

from ks.cartograph.live_capture import CapturedFrame
from ks.cartograph.mosaic import (
    grid_cell_order,
    grid_swipe_path,
    stitch_viewport_mosaic,
    world_to_panorama,
)
from pathlib import Path


def test_grid_cell_order_fills_square_serpentine():
    cells = grid_cell_order(2)
    assert len(cells) == 25  # (2*2+1)^2
    assert cells[0] == (-2, -2)
    assert (0, 0) in cells
    assert set(cells) == {(x, y) for x in range(-2, 3) for y in range(-2, 3)}
    # Serpentine: row y=-2 left→right, y=-1 right→left
    row_neg2 = [c for c in cells if c[1] == -2]
    assert row_neg2 == [(-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2)]
    row_neg1 = [c for c in cells if c[1] == -1]
    assert row_neg1 == [(2, -1), (1, -1), (0, -1), (-1, -1), (-2, -1)]


def test_grid_swipe_path_moves_one_axis_at_a_time():
    assert grid_swipe_path((0, 0), (2, 0)) == ["E", "E"]
    assert grid_swipe_path((0, 0), (0, -1)) == ["N"]
    assert grid_swipe_path((1, 1), (-1, -1)) == ["W", "W", "N", "N"]


def test_parse_grid_cell_rays_and_grid():
    from ks.cartograph.mosaic import parse_grid_cell

    assert parse_grid_cell("c0_center") == (0, 0)
    assert parse_grid_cell("E1") == (1, 0)
    assert parse_grid_cell("W2") == (-2, 0)
    assert parse_grid_cell("N1") == (0, -1)
    assert parse_grid_cell("S3") == (0, 3)
    assert parse_grid_cell("g_1_-1") == (1, -1)
    assert parse_grid_cell("c1_E") == (1, 0)


def _frame(name: str, vx: int, vy: int, color: tuple[int, int, int]) -> CapturedFrame:
    img = np.zeros((1920, 1080, 3), dtype=np.uint8)
    img[:] = color
    # bright center blob
    img[900:1020, 500:580] = (255, 255, 255)
    return CapturedFrame(
        name=name,
        path=Path(f"{name}.png"),
        viewport=(vx, vy),
        viewport_raw=f"X:{vx} Y:{vy}",
        image=img,
    )


def test_stitch_grid_named_frames_estimates_scale(tmp_path: Path):
    """Grid captures use g_{ex}_{ey} names; stitch must still place them."""
    frames = [
        _frame("c0_center", 100, 100, (40, 80, 40)),
        _frame("g_1_0", 108, 100, (80, 40, 40)),
        _frame("g_0_1", 100, 108, (40, 40, 80)),
        _frame("g_-1_0", 92, 100, (80, 80, 40)),
        _frame("g_0_-1", 100, 92, (40, 80, 80)),
    ]
    mosa = stitch_viewport_mosaic(frames, tmp_path / "panorama.png")
    px0, _ = world_to_panorama(100, 100, mosa)
    px_e, _ = world_to_panorama(108, 100, mosa)
    _, py_s = world_to_panorama(100, 108, mosa)
    _, py_n = world_to_panorama(100, 92, mosa)
    assert px_e > px0
    assert py_s > py_n


def test_filter_viewport_frames_drops_outliers():
    from ks.cartograph.mosaic import filter_viewport_frames

    frames = [
        _frame("c0_center", 1133, 110, (40, 80, 40)),
        _frame("g_1_0", 1141, 102, (80, 40, 40)),
        _frame("g_0_1", 16, 94, (40, 40, 80)),  # kingdom bleed
        _frame("g_-1_-2", 1144, 1499, (80, 80, 40)),  # OCR garbage Y
        _frame("g_-1_0", 1124, 119, (40, 80, 80)),
    ]
    kept = filter_viewport_frames(frames, max_dev=80)
    names = {f.name for f in kept}
    assert names == {"c0_center", "g_1_0", "g_-1_0"}


def test_stitch_places_east_frame_to_the_right(tmp_path: Path):
    frames = [
        _frame("c0_center", 100, 100, (40, 80, 40)),
        _frame("E1", 108, 100, (80, 40, 40)),
        _frame("W1", 92, 100, (40, 40, 80)),
    ]
    out = tmp_path / "panorama.png"
    mosa = stitch_viewport_mosaic(frames, out)
    assert out.is_file()
    assert mosa.image.shape[0] > 100 and mosa.image.shape[1] > 100
    px, py = world_to_panorama(100, 100, mosa)
    assert abs(px - mosa.origin_x) < 1.0
    assert abs(py - mosa.origin_y) < 1.0
    px_e, _ = world_to_panorama(108, 100, mosa)
    assert px_e > px


def test_warp_iso_writes_bitmap(tmp_path: Path):
    from ks.cartograph.mosaic import warp_mosaic_to_isometric

    frames = [
        _frame("c0_center", 100, 100, (40, 120, 40)),
        _frame("E1", 108, 100, (80, 40, 40)),
    ]
    mosa = stitch_viewport_mosaic(frames, tmp_path / "panorama.png")
    iso_path = tmp_path / "panorama-iso.png"
    img, w, h, ox, oy = warp_mosaic_to_isometric(
        mosa, min_x=95, max_x=110, min_y=95, max_y=105, out_path=iso_path
    )
    assert iso_path.is_file()
    assert img.shape[0] == int(h) and img.shape[1] == int(w)
    assert w > 100 and h > 100
