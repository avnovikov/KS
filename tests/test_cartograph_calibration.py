"""Robust world-to-pixel calibration for cartograph stitching."""

import numpy as np
import pytest

from ks.cartograph.calibration import (
    CalibrationObservation,
    fit_frame_offsets,
    fit_world_to_pixel,
    measure_scale_from_observations_on_frame,
    measure_scale_from_two_points,
    sample_indices_for_scale_checks,
    validate_scale_from_two_chords,
)


def _observation(
    frame: str,
    world_x: float,
    world_y: float,
    *,
    weight: float = 1.0,
) -> CalibrationObservation:
    return CalibrationObservation(
        frame=frame,
        world_x=world_x,
        world_y=world_y,
        pixel_x=92.0 * world_x - 11.0 * world_y + 30.0,
        pixel_y=7.0 * world_x + 68.0 * world_y - 20.0,
        weight=weight,
    )


def test_fit_world_to_pixel_recovers_axes_and_rejects_outlier():
    observations = [
        _observation("center", 0, 0),
        _observation("east", 2, 0),
        _observation("south", 0, 3),
        _observation("diagonal", 2, 3),
        CalibrationObservation("bad-ocr", 9, 9, 4000, -3000, 0.2),
    ]

    fit = fit_world_to_pixel(observations, residual_limit_px=20.0)

    assert np.allclose(
        fit.matrix,
        np.array([[92.0, -11.0, 30.0], [7.0, 68.0, -20.0]]),
        atol=1.0,
    )
    assert {item.frame for item in fit.rejected} == {"bad-ocr"}


def test_fit_world_to_pixel_requires_two_dimensional_evidence():
    observations = [
        _observation("center", 0, 0),
        _observation("east-1", 1, 0),
        _observation("east-2", 2, 0),
    ]

    with pytest.raises(ValueError, match="both world axes"):
        fit_world_to_pixel(observations)


def test_fit_frame_offsets_uses_exact_objects_as_primary_geometry():
    matrix = np.array([[90.0, -12.0], [8.0, 70.0]])
    biases = {"center": np.array([300.0, 500.0]), "east": np.array([210.0, 505.0])}
    observations = []
    for frame, bias in biases.items():
        for _name, world in (
            ("city-a", (1045.0, 113.0)),
            ("city-b", (1048.0, 118.0)),
            ("city-c", (1046.0, 117.0)),
        ):
            pixel = matrix @ np.asarray(world) + bias
            observations.append(
                CalibrationObservation(
                    frame=frame,
                    world_x=world[0],
                    world_y=world[1],
                    pixel_x=pixel[0],
                    pixel_y=pixel[1],
                )
            )

    fit = fit_frame_offsets(observations, reference_frame="center")

    assert np.allclose(fit.matrix, matrix)
    assert np.allclose(fit.frame_offsets["center"], (0.0, 0.0))
    assert np.allclose(fit.frame_offsets["east"], (90.0, -5.0))


def test_measure_scale_from_two_points():
    """Two known points → px/tile along that chord."""
    # 10 tiles east at 50 px/tile → 500 px
    seg = measure_scale_from_two_points(
        label_a="a",
        world_a=(100.0, 200.0),
        pixel_a=(0.0, 0.0),
        label_b="b",
        world_b=(110.0, 200.0),
        pixel_b=(500.0, 0.0),
    )
    assert seg.world_length_tiles == pytest.approx(10.0)
    assert seg.pixel_length_px == pytest.approx(500.0)
    assert seg.px_per_tile == pytest.approx(50.0)


def test_measure_scale_rejects_identical_world():
    with pytest.raises(ValueError, match="distinct world"):
        measure_scale_from_two_points(
            label_a="a",
            world_a=(1.0, 1.0),
            pixel_a=(0.0, 0.0),
            label_b="b",
            world_b=(1.0, 1.0),
            pixel_b=(10.0, 0.0),
        )


def test_validate_scale_from_two_independent_chords():
    chord_x = measure_scale_from_two_points(
        label_a="c",
        world_a=(0.0, 0.0),
        pixel_a=(0.0, 0.0),
        label_b="e",
        world_b=(8.0, 0.0),
        pixel_b=(400.0, 40.0),
    )
    chord_y = measure_scale_from_two_points(
        label_a="c",
        world_a=(0.0, 0.0),
        pixel_a=(0.0, 0.0),
        label_b="s",
        world_b=(0.0, 8.0),
        pixel_b=(40.0, 440.0),
    )
    result = validate_scale_from_two_chords(chord_x, chord_y)
    assert result.ok
    assert "ok" in result.detail


def test_validate_scale_rejects_parallel_chords():
    a = measure_scale_from_two_points(
        label_a="c",
        world_a=(0.0, 0.0),
        pixel_a=(0.0, 0.0),
        label_b="e1",
        world_b=(5.0, 0.0),
        pixel_b=(250.0, 0.0),
    )
    b = measure_scale_from_two_points(
        label_a="c",
        world_a=(0.0, 0.0),
        pixel_a=(0.0, 0.0),
        label_b="e2",
        world_b=(10.0, 0.0),
        pixel_b=(500.0, 0.0),
    )
    result = validate_scale_from_two_chords(a, b)
    assert not result.ok
    assert "parallel" in result.detail


def test_sample_indices_for_scale_checks_about_20_percent():
    idxs = sample_indices_for_scale_checks(25, fraction=0.2, min_samples=2, max_samples=12)
    assert 2 <= len(idxs) <= 12
    assert idxs == sorted(idxs)
    assert idxs[0] == 0
    assert idxs[-1] == 24


def test_measure_scale_from_observations_on_same_screenshot():
    obs = [
        CalibrationObservation("f0", 100, 200, 10, 20),
        CalibrationObservation("f0", 110, 200, 510, 20),
        CalibrationObservation("f0", 100, 205, 10, 270),
    ]
    seg = measure_scale_from_observations_on_frame(obs)
    # Farthest world pair is (100,200)-(110,200) = 10 tiles → 50 px/tile
    assert seg.px_per_tile == pytest.approx(50.0)
