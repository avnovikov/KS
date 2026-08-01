"""Tests for viewport mosaic stitching."""

import numpy as np
import pytest

from ks.cartograph.live_capture import CapturedFrame
from ks.cartograph.mosaic import (
    MosaicResult,
    grid_cell_order,
    grid_swipe_path,
    mosaic_projection,
    panorama_world_bounds,
    stitch_grid_lattice,
    stitch_viewport_mosaic,
    warp_mosaic_to_isometric,
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


def _mosaic(
    tmp_path: Path,
    *,
    matrix: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> MosaicResult:
    fields = dict(
        image=np.zeros((80, 120, 3), dtype=np.uint8),
        path=tmp_path / "panorama.png",
        center=(100, 200),
        scale_x=10.0,
        scale_y=20.0,
        origin_x=60.0,
        origin_y=40.0,
        band_w=120,
        band_h=80,
    )
    if matrix is not None:
        fields["world_to_pixel_matrix"] = matrix
    return MosaicResult(**fields)


def test_mosaic_result_affine_metadata_is_optional(tmp_path: Path):
    mosaic = _mosaic(tmp_path)

    assert mosaic.world_to_pixel_matrix is None


@pytest.mark.parametrize(
    "matrix",
    [
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((1.0, 2.0), (2.0, 4.0)),
        ((1.0, np.nan), (0.0, 1.0)),
        ((1.0, 1.0), (1.0, 1.0 + 1e-14)),
    ],
)
def test_mosaic_result_rejects_invalid_affine_metadata(
    tmp_path: Path, matrix: object
):
    with pytest.raises(ValueError):
        _mosaic(tmp_path, matrix=matrix)  # type: ignore[arg-type]


def test_mosaic_result_deeply_canonicalizes_affine_metadata(tmp_path: Path):
    source = [[12.0, -8.0], [6.0, 5.0]]

    mosaic = _mosaic(tmp_path, matrix=source)  # type: ignore[arg-type]
    source[0][0] = 999.0

    assert mosaic.world_to_pixel_matrix == ((12.0, -8.0), (6.0, 5.0))
    with pytest.raises(TypeError):
        mosaic.world_to_pixel_matrix[0][0] = 999.0  # type: ignore[index]


def test_world_to_panorama_follows_diagonal_basis_vectors(tmp_path: Path):
    mosaic = _mosaic(tmp_path, matrix=((12.0, -8.0), (6.0, 5.0)))

    assert world_to_panorama(101, 200, mosaic) == pytest.approx((72.0, 46.0))
    assert world_to_panorama(100, 201, mosaic) == pytest.approx((52.0, 45.0))
    assert world_to_panorama(102, 203, mosaic) == pytest.approx((60.0, 67.0))


def test_panorama_world_bounds_inverse_projects_all_image_corners(tmp_path: Path):
    mosaic = _mosaic(tmp_path, matrix=((12.0, -8.0), (6.0, 5.0)))
    projection = mosaic_projection(mosaic)
    expected_corners = [
        projection.world_from_pixel(px, py)
        for px, py in ((0.0, 0.0), (120.0, 0.0), (120.0, 80.0), (0.0, 80.0))
    ]
    expected_x, expected_y = zip(*expected_corners, strict=True)

    assert panorama_world_bounds(mosaic) == pytest.approx(
        (min(expected_x), min(expected_y), max(expected_x), max(expected_y))
    )


def test_mosaic_projection_uses_legacy_scalar_fallback(tmp_path: Path):
    mosaic = _mosaic(tmp_path)

    projection = mosaic_projection(mosaic)

    assert projection.matrix == ((10.0, 0.0), (0.0, 20.0))
    assert world_to_panorama(102, 203, mosaic) == pytest.approx((80.0, 100.0))


def test_calibrated_stitch_ignores_landmarks_and_matches_published_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from ks.cartograph.calibration import AffineCalibration
    import ks.cartograph.mosaic as mosaic_module

    frames = [
        _frame("c0_center", 100, 100, (40, 80, 40)),
        _frame("g_1_0", 102, 100, (80, 40, 40)),
        _frame("g_0_1", 100, 103, (40, 40, 80)),
    ]
    matrix = np.array([[12.0, -8.0, 4.0], [6.0, 5.0, -3.0]])
    calibration = AffineCalibration(matrix=matrix, accepted=(), rejected=())
    pasted_origins: list[tuple[int, int]] = []

    def reject_landmark_refinement(*args, **kwargs):
        raise AssertionError("exact calibration must bypass landmark refinement")

    def record_paste(*args, x0: int, y0: int, **kwargs):
        pasted_origins.append((x0, y0))

    monkeypatch.setattr(
        mosaic_module, "place_grid_by_landmarks", reject_landmark_refinement
    )
    monkeypatch.setattr(
        mosaic_module, "_paste_band_structure_aware", record_paste
    )

    mosaic = stitch_grid_lattice(
        frames,
        tmp_path / "panorama.png",
        calibration=calibration,
    )

    assert np.allclose(mosaic.world_to_pixel_matrix, matrix[:, :2])
    expected_origins = {
        (
            round(world_to_panorama(*frame.viewport, mosaic)[0] - mosaic.band_w / 2),
            round(world_to_panorama(*frame.viewport, mosaic)[1] - mosaic.band_h / 2),
        )
        for frame in frames
    }
    assert set(pasted_origins) == expected_origins


def test_stitch_rejects_competing_placement_authorities(tmp_path: Path):
    from ks.cartograph.calibration import AffineCalibration

    frames = [
        _frame("c0_center", 100, 100, (40, 80, 40)),
        _frame("g_1_0", 102, 100, (80, 40, 40)),
        _frame("g_0_1", 100, 103, (40, 40, 80)),
    ]
    calibration = AffineCalibration(
        matrix=np.array([[12.0, -8.0, 4.0], [6.0, 5.0, -3.0]]),
        accepted=(),
        rejected=(),
    )
    frame_offsets = {
        "c0_center": (0.0, 0.0),
        "g_1_0": (24.0, 12.0),
        "g_0_1": (-24.0, 15.0),
    }

    with pytest.raises(
        ValueError,
        match="calibration and frame_offsets are competing placement authorities",
    ):
        stitch_grid_lattice(
            frames,
            tmp_path / "panorama.png",
            calibration=calibration,
            frame_offsets=frame_offsets,
        )


def test_stitch_frame_offsets_publish_world_to_pixel_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import ks.cartograph.mosaic as mosaic_module

    frames = [
        _frame("c0_center", 1116, 287, (40, 80, 40)),
        _frame("g_1_0", 1118, 287, (80, 40, 40)),
    ]
    frame_offsets = {
        "c0_center": (0.0, 0.0),
        "g_1_0": (120.0, -5.0),
    }
    matrix = ((113.58, -113.35), (-81.01, -82.87))
    pasted: list[tuple[int, int]] = []

    def record_paste(*args, x0: int, y0: int, **kwargs):
        pasted.append((x0, y0))

    monkeypatch.setattr(mosaic_module, "_paste_band_structure_aware", record_paste)

    mosaic = stitch_grid_lattice(
        frames,
        tmp_path / "panorama.png",
        frame_offsets=frame_offsets,
        world_to_pixel_matrix=matrix,
    )

    assert np.allclose(mosaic.world_to_pixel_matrix, matrix)
    assert len(pasted) == 2
    # Relative placement must follow frame_offsets, not viewport calibration.
    dx = abs(pasted[0][0] - pasted[1][0])
    dy = abs(pasted[0][1] - pasted[1][1])
    assert dx == pytest.approx(120, abs=1)
    assert dy == pytest.approx(5, abs=1)


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


def test_filter_viewport_frames_drops_near_duplicates():
    from ks.cartograph.mosaic import filter_viewport_frames

    frames = [
        _frame("c0_center", 700, 800, (40, 80, 40)),
        _frame("g_1_0", 704, 796, (80, 40, 40)),
        _frame("g_2_0", 704, 796, (40, 40, 80)),  # exact dup of g_1_0
        _frame("g_0_1", 698, 804, (80, 80, 40)),
        _frame("g_-1_0", 697, 804, (40, 80, 80)),  # near-dup of g_0_1
    ]
    kept = filter_viewport_frames(
        frames, max_dev=80, dup_tol=1.0, max_residual=None
    )
    names = {f.name for f in kept}
    assert "c0_center" in names
    assert "g_1_0" in names or "g_2_0" in names
    assert not ({"g_1_0", "g_2_0"} <= names)
    assert not ({"g_0_1", "g_-1_0"} <= names)
    assert len(kept) == 3


def test_filter_viewport_frames_drops_linear_residual_outliers():
    from ks.cartograph.mosaic import filter_viewport_frames

    # Coherent lattice around (700,800) with one OCR bomb that still passes median.
    frames = [
        _frame("c0_center", 700, 800, (40, 80, 40)),
        _frame("g_1_0", 704, 796, (80, 40, 40)),
        _frame("g_-1_0", 696, 804, (40, 40, 80)),
        _frame("g_0_1", 704, 804, (80, 80, 40)),
        _frame("g_0_-1", 696, 796, (40, 80, 80)),
        _frame("g_2_1", 760, 820, (90, 90, 40)),  # residual vs cell fit
    ]
    kept = filter_viewport_frames(frames, max_dev=80, max_residual=12.0)
    names = {f.name for f in kept}
    assert "g_2_1" not in names
    assert {"c0_center", "g_1_0", "g_-1_0", "g_0_1", "g_0_-1"} <= names


def test_grid_stitch_filters_viewport_outliers(tmp_path: Path, monkeypatch):
    """Grid path must audit frames (filter was previously non-grid only)."""
    import ks.cartograph.mosaic as mosaic_module

    frames = [
        _frame("c0_center", 700, 800, (40, 80, 40)),
        _frame("g_1_0", 704, 796, (80, 40, 40)),
        _frame("g_0_1", 704, 804, (40, 40, 80)),
        _frame("g_-1_0", 16, 800, (80, 80, 40)),  # kingdom bleed
    ]
    seen: list[int] = []

    real_filter = mosaic_module.filter_viewport_frames

    def tracking_filter(frames_in, **kwargs):
        kept = real_filter(frames_in, **kwargs)
        seen.append(len(kept))
        return kept

    monkeypatch.setattr(mosaic_module, "filter_viewport_frames", tracking_filter)
    mosaic = stitch_viewport_mosaic(frames, tmp_path / "panorama.png")
    assert seen and seen[0] == 3
    assert mosaic.world_to_pixel_matrix is not None


def test_place_frames_by_world_affine_relative_offsets():
    from ks.cartograph.mosaic import place_frames_by_world_affine

    frames = [
        _frame("c0_center", 100, 200, (40, 80, 40)),
        _frame("g_1_0", 104, 196, (80, 40, 40)),
    ]
    # M maps (dx, dy) -> (10*dx - 8*dy, 6*dx + 5*dy)
    matrix = ((10.0, -8.0), (6.0, 5.0))
    placed = place_frames_by_world_affine(frames, matrix, center=(100.0, 200.0))
    assert placed["c0_center"] == pytest.approx((0.0, 0.0))
    # world delta (4, -4) → (10*4 -8*(-4), 6*4 + 5*(-4)) = (72, 4)
    assert placed["g_1_0"] == pytest.approx((72.0, 4.0))


def test_world_affine_grid_restitch_publishes_matrix_and_offsets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import ks.cartograph.mosaic as mosaic_module

    frames = [
        _frame("c0_center", 100, 100, (40, 80, 40)),
        _frame("g_1_0", 104, 96, (80, 40, 40)),
        _frame("g_0_1", 104, 104, (40, 40, 80)),
        _frame("g_-1_0", 96, 104, (80, 80, 40)),
        _frame("g_0_-1", 96, 96, (40, 80, 80)),
    ]
    pasted: list[tuple[int, int]] = []

    def record_paste(*args, x0: int, y0: int, **kwargs):
        pasted.append((x0, y0))

    monkeypatch.setattr(mosaic_module, "_paste_band_structure_aware", record_paste)
    monkeypatch.setattr(
        mosaic_module,
        "place_grid_by_landmarks",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("default grid restitch must not use landmark lattice")
        ),
    )

    mosaic = stitch_viewport_mosaic(frames, tmp_path / "panorama.png")
    assert mosaic.world_to_pixel_matrix is not None
    assert len(pasted) == 5

    # Relative offset of g_1_0 vs center must match M @ (vp - center).
    m = np.asarray(mosaic.world_to_pixel_matrix, dtype=float)
    expected = m @ np.array([4.0, -4.0])
    # Recover paste origins relative to center paste (order is structure-sorted).
    # Use projection instead: world→panorama delta equals M @ world_delta.
    px0, py0 = world_to_panorama(100, 100, mosaic)
    px1, py1 = world_to_panorama(104, 96, mosaic)
    assert (px1 - px0, py1 - py0) == pytest.approx(tuple(expected), abs=1.0)


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


def test_warp_iso_samples_panorama_through_affine_projection(tmp_path: Path):
    source = np.zeros((60, 60, 3), dtype=np.uint8)
    source[22, 25] = (255, 255, 255)
    mosaic = MosaicResult(
        image=source,
        path=tmp_path / "panorama.png",
        center=(0, 0),
        scale_x=11.0,
        scale_y=13.0,
        origin_x=20.0,
        origin_y=20.0,
        band_w=60,
        band_h=60,
        world_to_pixel_matrix=((5.0, -3.0), (2.0, 4.0)),
    )

    image, _, _, origin_x, origin_y = warp_mosaic_to_isometric(
        mosaic,
        min_x=0,
        max_x=1,
        min_y=0,
        max_y=1,
    )
    sample_x = round(origin_x + 18.0)
    sample_y = round(origin_y + 10.0)

    assert image[sample_y, sample_x] == pytest.approx((255, 255, 255))


def test_fit_world_matrix_uses_ncc_two_point_edges(monkeypatch: pytest.MonkeyPatch):
    """M must come from OCR world Δ + NCC pixel Δ, not overlap*band heuristic."""
    import ks.cartograph.mosaic as mosaic_module
    from ks.cartograph.mosaic import fit_world_to_pixel_matrix_from_viewports

    true_m = np.array([[40.0, 10.0], [12.0, 55.0]], dtype=float)
    w1 = np.array([4.0, -4.0])
    w2 = np.array([-3.0, -8.0])
    p1 = true_m @ w1
    p2 = true_m @ w2

    monkeypatch.setattr(
        mosaic_module,
        "_collect_ncc_world_pixel_edges",
        lambda *a, **k: [(w1, p1), (w2, p2)],
    )
    frames = [
        _frame("c0_center", 700, 800, (40, 80, 40)),
        _frame("g_1_0", 704, 796, (80, 40, 40)),
        _frame("g_0_1", 697, 792, (40, 40, 80)),
    ]
    matrix = fit_world_to_pixel_matrix_from_viewports(frames, 400, 800, overlap=0.55)
    recovered = np.asarray(matrix, dtype=float)
    assert recovered == pytest.approx(true_m, abs=0.5)
