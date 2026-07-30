"""Tests for never-touch crop + grid-lattice mosaic stitching."""

from pathlib import Path

import numpy as np
import pytest

from ks.cartograph.calibration import AffineCalibration
from ks.cartograph.live_capture import CapturedFrame
from ks.cartograph.mask import bluestacks_mask_config, mask_and_crop
from ks.cartograph.mosaic import (
    calibrate_grid_pixel_steps,
    calibrated_grid_steps,
    parse_grid_cell,
    stitch_grid_lattice,
)


def test_bluestacks_band_has_almost_no_fill_holes():
    """Never-touch: side HUD cropped away; only small on-map bubbles remain fill."""
    cfg = bluestacks_mask_config()
    img = np.full((1920, 1080, 3), 120, dtype=np.uint8)
    band = mask_and_crop(img, cfg)
    fill = np.array(cfg.fill, dtype=np.uint8)
    hole = float(np.all(band == fill, axis=2).mean())
    assert band.shape[1] < 1080
    # Was ~47% when side chrome lived inside the band; bubbles only now.
    assert hole < 0.12, hole


def test_parse_grid_cell():
    assert parse_grid_cell("c0_center") == (0, 0)
    assert parse_grid_cell("g_0_0") == (0, 0)
    assert parse_grid_cell("g_2_-1") == (2, -1)
    assert parse_grid_cell("E1") is None


def _frame(name: str, vx: int, vy: int, color: tuple[int, int, int]) -> CapturedFrame:
    img = np.zeros((1920, 1080, 3), dtype=np.uint8)
    img[:] = color
    # unique textured blob so visual checks have content
    img[900:1100, 400:700] = (255, 255, 255)
    return CapturedFrame(
        name=name,
        path=Path(f"{name}.png"),
        viewport=(vx, vy),
        viewport_raw=f"X:{vx} Y:{vy}",
        image=img,
    )


def test_calibrate_steps_from_controlled_neighbors():
    """E neighbor at +10,-9 tiles → pixel step follows that lattice."""
    frames = [
        _frame("c0_center", 100, 100, (40, 80, 40)),
        _frame("g_1_0", 110, 91, (80, 40, 40)),
        _frame("g_-1_0", 90, 109, (40, 40, 80)),
        _frame("g_0_1", 91, 85, (80, 80, 40)),
        _frame("g_0_-1", 109, 115, (40, 80, 80)),
    ]
    pe, ps = calibrate_grid_pixel_steps(
        frames, band_w=756, band_h=1076, refine=False
    )
    # One E step should move roughly half a band (overlap target).
    assert 200 < abs(pe[0]) < 600, pe
    assert abs(pe[1]) > 100, pe
    # S step nonzero
    assert abs(ps[0]) + abs(ps[1]) > 200, ps


def test_calibrated_grid_steps_use_independent_world_axes():
    frames = {
        (0, 0): _frame("c0_center", 100, 100, (40, 80, 40)),
        (1, 0): _frame("g_1_0", 102, 100, (80, 40, 40)),
        (0, 1): _frame("g_0_1", 100, 103, (40, 40, 80)),
    }
    calibration = AffineCalibration(
        matrix=np.array([[90.0, -10.0, 12.0], [5.0, 70.0, -8.0]]),
        accepted=(),
        rejected=(),
    )

    pe, ps = calibrated_grid_steps(frames, calibration)

    assert np.allclose(pe, (180.0, 10.0))
    assert np.allclose(ps, (-30.0, 210.0))


def test_lattice_stitch_places_east_right_of_center(tmp_path: Path):
    frames = [
        _frame("c0_center", 100, 100, (40, 80, 40)),
        _frame("g_1_0", 110, 91, (80, 40, 40)),
        _frame("g_-1_0", 90, 109, (40, 40, 80)),
        _frame("g_0_1", 91, 85, (80, 80, 40)),
        _frame("g_0_-1", 109, 115, (40, 80, 80)),
    ]
    mosa = stitch_grid_lattice(
        frames, tmp_path / "panorama.png", use_landmarks=False
    )
    assert mosa.image.shape[0] > 100 and mosa.image.shape[1] > 100
    # East cell origin should be to the right of center origin in mosaic math
    pe, _ps = calibrate_grid_pixel_steps(
        frames, mosa.band_w, mosa.band_h, refine=False
    )
    assert pe[0] > 0 or pe[1] != 0  # diagonal OK; must not be zero


def test_structure_paste_keeps_building_over_grass():
    """Misaligned grass neighbor must not stamp out a city blob."""
    from ks.cartograph.mosaic import _paste_band_structure_aware, _structure_score

    fill = np.array([0, 0, 0], dtype=np.uint8)
    h, w = 120, 120
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    weight = np.zeros((h, w), dtype=np.float32)
    structure = np.zeros((h, w), dtype=np.float32)
    soft = np.ones((h, w), dtype=np.float32)

    city = np.full((h, w, 3), (40, 160, 40), dtype=np.uint8)  # grass BGR
    # High-contrast building block (blue-ish roof in BGR)
    city[40:80, 40:80] = (200, 40, 40)
    city[85:95, 45:75] = (10, 10, 10)  # nameplate below, not on sample pixel
    _paste_band_structure_aware(
        canvas, weight, structure, city, soft, x0=0, y0=0, fill=fill
    )
    assert int(canvas[60, 60, 0]) > 150  # blue channel

    grass = np.full((h, w, 3), (50, 170, 50), dtype=np.uint8)
    # Stronger soft weight, but flat grass — must not wipe the building.
    soft2 = soft * 2.0
    _paste_band_structure_aware(
        canvas, weight, structure, grass, soft2, x0=0, y0=0, fill=fill
    )
    assert int(canvas[60, 60, 0]) > 150, canvas[60, 60]
    assert _structure_score(city)[60, 60] > _structure_score(grass)[60, 60]


def test_normalize_and_pair_offsets_from_shared_names():
    from ks.cartograph.landmarks import (
        NameLandmark,
        landmark_pair_offsets,
        normalize_landmark_name,
    )

    assert normalize_landmark_name("lord382445709") == "lord382445709"
    assert normalize_landmark_name("Alliance Woodmill") == "ambig:alliancewoodmill"
    assert normalize_landmark_name("noise") is None

    # Ambiguous mills must not create cross-frame glue.
    mill_lms = {
        (-1, -2): [NameLandmark("ambig:alliancewoodmill", 190.0, 544.0, 0.9)],
        (0, 1): [NameLandmark("ambig:alliancewoodmill", 372.0, 164.0, 0.9)],
    }
    assert landmark_pair_offsets(mill_lms) == []

    lms = {
        (-1, 0): [NameLandmark("lord111222", 100.0, 200.0, 0.9)],
        (1, 0): [NameLandmark("lord111222", 400.0, 250.0, 0.9)],
    }
    cons = landmark_pair_offsets(lms)
    assert len(cons) == 1
    ca, cb, dx, dy, w = cons[0]
    assert {ca, cb} == {(-1, 0), (1, 0)}
    assert w > 1.0
    if ca == (-1, 0):
        assert abs(dx - (-300.0)) < 1e-6 and abs(dy - (-50.0)) < 1e-6
    else:
        assert abs(dx - 300.0) < 1e-6 and abs(dy - 50.0) < 1e-6

def test_place_grid_uses_shared_landmark_over_lattice():
    """Shared lord name should pull interior cells off a pure lattice."""
    from ks.cartograph.landmarks import NameLandmark
    from ks.cartograph.mosaic import place_grid_by_landmarks

    pe, ps = (189.0, -225.0), (-277.5, -243.5)
    frames = {
        (-2, 0): _frame("g_-2_0", 80, 120, (40, 80, 40)),
        (-1, 0): _frame("g_-1_0", 100, 100, (40, 80, 40)),
        (0, 0): _frame("c0_center", 110, 90, (80, 40, 40)),
        (1, 0): _frame("g_1_0", 120, 80, (40, 40, 80)),
        (2, 0): _frame("g_2_0", 140, 70, (80, 80, 40)),
    }
    for fr in frames.values():
        fr.image[800:1000, 300:500] = (30, 180, 30)
        fr.image[900:950, 400:450] = (200, 50, 50)

    landmarks = {
        (-1, 0): [NameLandmark("lord111", 100.0, 200.0, 0.95)],
        (1, 0): [NameLandmark("lord111", 400.0, 250.0, 0.95)],
    }
    pos = place_grid_by_landmarks(
        frames,
        pe,
        ps,
        band_w=756,
        band_h=1076,
        landmarks_by_cell=landmarks,
        use_ncc=False,
    )
    dx = pos[(1, 0)][0] - pos[(-1, 0)][0]
    dy = pos[(1, 0)][1] - pos[(-1, 0)][1]
    assert abs(dx - (-300.0)) < 50, (dx, dy, pos)
    assert abs(dy - (-50.0)) < 50, (dx, dy, pos)
