"""Tests for cartograph pixel↔world projection."""

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from ks.cartograph.project import (
    AffineProjection,
    pixel_from_world,
    round_tile,
    world_from_pixel,
)


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


def test_affine_projection_uses_both_diamond_basis_vectors() -> None:
    projection = AffineProjection(
        center=(10.0, 20.0),
        pixel_origin=(100.0, 200.0),
        matrix=np.array([[4.0, -2.0], [2.0, 2.0]]),
    )

    assert projection.pixel_from_world(13.0, 22.0) == pytest.approx((108.0, 210.0))


def test_affine_projection_round_trip_recovers_world_coordinates() -> None:
    projection = AffineProjection(
        center=(700.0, 820.0),
        pixel_origin=(540.0, 833.0),
        matrix=np.array([[95.7, -99.5], [-67.7, -68.1]]),
    )

    pixel = projection.pixel_from_world(705.25, 823.75)

    assert projection.world_from_pixel(*pixel) == pytest.approx(
        (705.25, 823.75), abs=1e-9
    )


def test_tile_polygon_projects_four_world_corners() -> None:
    projection = AffineProjection(
        center=(10.0, 20.0),
        pixel_origin=(100.0, 200.0),
        matrix=np.array([[4.0, -2.0], [2.0, 2.0]]),
    )

    np.testing.assert_allclose(
        projection.tile_polygon(10.0, 20.0),
        ((99.0, 198.0), (103.0, 200.0), (101.0, 202.0), (97.0, 200.0)),
    )


def test_world_bounds_inverse_projects_all_four_image_corners() -> None:
    projection = AffineProjection(
        center=(0.0, 0.0),
        pixel_origin=(0.0, 0.0),
        matrix=np.array([[2.0, -1.0], [1.0, 1.0]]),
    )

    assert projection.world_bounds_for_image(4, 3) == pytest.approx(
        (0.0, -4.0 / 3.0, 7.0 / 3.0, 2.0)
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_message"),
    [
        ("center", (1.0,), "center must contain exactly two values"),
        ("pixel_origin", (0.0, np.inf), "pixel_origin must contain finite values"),
        ("matrix", np.eye(3), "matrix must have shape \\(2, 2\\)"),
        (
            "matrix",
            np.array([[1.0, np.nan], [0.0, 1.0]]),
            "matrix must contain finite values",
        ),
        (
            "matrix",
            np.array([[1.0, 2.0], [2.0, 4.0]]),
            "matrix must be invertible",
        ),
    ],
)
def test_affine_projection_rejects_invalid_geometry(
    field_name: str,
    invalid_value: object,
    expected_message: str,
) -> None:
    arguments = {
        "center": (0.0, 0.0),
        "pixel_origin": (0.0, 0.0),
        "matrix": np.eye(2),
    }
    arguments[field_name] = invalid_value

    with pytest.raises(ValueError, match=expected_message):
        AffineProjection(**arguments)


@pytest.mark.parametrize(("width", "height"), [(0, 10), (10, 0), (-1, 10)])
def test_world_bounds_rejects_invalid_image_dimensions(
    width: int, height: int
) -> None:
    projection = AffineProjection(
        center=(0.0, 0.0),
        pixel_origin=(0.0, 0.0),
        matrix=np.eye(2),
    )

    with pytest.raises(ValueError, match="image dimensions must be positive"):
        projection.world_bounds_for_image(width, height)


def test_affine_projection_is_frozen() -> None:
    projection = AffineProjection(
        center=(0.0, 0.0),
        pixel_origin=(0.0, 0.0),
        matrix=np.eye(2),
    )

    with pytest.raises(FrozenInstanceError):
        projection.center = (1.0, 1.0)


def test_affine_projection_rejects_matrix_with_non_finite_inverse() -> None:
    numerically_degenerate_matrix = np.array([[1e-320, 0.0], [0.0, 1.0]])

    with pytest.raises(ValueError, match="matrix inverse must contain finite values"):
        AffineProjection(
            center=(0.0, 0.0),
            pixel_origin=(0.0, 0.0),
            matrix=numerically_degenerate_matrix,
        )


def test_affine_projection_rejects_ill_conditioned_matrix() -> None:
    numerically_degenerate_matrix = np.array(
        [[1.0, 1.0], [1.0, 1.0 + 1e-14]]
    )

    with pytest.raises(ValueError, match="matrix must be numerically stable"):
        AffineProjection(
            center=(0.0, 0.0),
            pixel_origin=(0.0, 0.0),
            matrix=numerically_degenerate_matrix,
        )


def test_equal_affine_projections_have_equal_hashes_for_signed_zero() -> None:
    positive_zero_projection = AffineProjection(
        center=(0.0, 0.0),
        pixel_origin=(0.0, 0.0),
        matrix=((1.0, 0.0), (0.0, 1.0)),
    )
    negative_zero_projection = AffineProjection(
        center=(-0.0, 0.0),
        pixel_origin=(0.0, -0.0),
        matrix=((1.0, -0.0), (0.0, 1.0)),
    )

    assert positive_zero_projection == negative_zero_projection
    assert hash(positive_zero_projection) == hash(negative_zero_projection)


def test_affine_projection_exposes_matrix_as_immutable_values() -> None:
    projection = AffineProjection(
        center=(0.0, 0.0),
        pixel_origin=(0.0, 0.0),
        matrix=np.eye(2),
    )

    assert isinstance(projection.matrix, tuple)
    with pytest.raises(TypeError):
        projection.matrix[0][0] = 2.0


def test_diamond_tile_sides_angles_and_affine_for_each_tile():
    from ks.cartograph.project import DiamondTileSides

    # +X goes right-down, +Y goes left-down (classic iso diamond).
    sides = DiamondTileSides(side_x=(40.0, 20.0), side_y=(-30.0, 25.0))
    assert sides.length_x == pytest.approx(np.hypot(40, 20))
    assert sides.angle_x_deg == pytest.approx(np.degrees(np.arctan2(20, 40)))
    assert sides.angle_y_deg == pytest.approx(np.degrees(np.arctan2(25, -30)))
    assert 0.0 < sides.included_angle_deg < 180.0

    # Every tile uses the same sides in its affine.
    a00 = sides.affine_for_tile(10, 20, pixel_origin=(100, 200), center=(10, 20))
    assert a00[0, 2] == pytest.approx(100.0)
    assert a00[1, 2] == pytest.approx(200.0)
    # Local (1,0) lands at origin + side_x
    assert a00[0, 0] == pytest.approx(40.0) and a00[1, 0] == pytest.approx(20.0)

    a11 = sides.affine_for_tile(11, 21, pixel_origin=(100, 200), center=(10, 20))
    # Tile (11,21) origin = (100,200) + side_x + side_y
    assert a11[0, 2] == pytest.approx(100 + 40 - 30)
    assert a11[1, 2] == pytest.approx(200 + 20 + 25)
