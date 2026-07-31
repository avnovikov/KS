"""Robust world-to-pixel calibration for cartograph stitching."""

import numpy as np
import pytest

from ks.cartograph.calibration import (
    CalibrationObservation,
    fit_frame_offsets,
    fit_world_to_pixel,
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
