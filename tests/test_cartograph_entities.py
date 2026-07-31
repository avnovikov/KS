"""Tests for provenance-aware cartograph entity catalog."""

from __future__ import annotations

import numpy as np
import pytest

from ks.cartograph.entities import (
    EntityCatalogEntry,
    EntityObservation,
    detect_frame_observations,
    merge_entity_observations,
    project_observation,
)
from ks.cartograph.project import AffineProjection


def _projection() -> AffineProjection:
    return AffineProjection(
        center=(1116.0, 287.0),
        pixel_origin=(1000.0, 1000.0),
        matrix=((100.0, -100.0), (-80.0, -80.0)),
    )


def test_project_observation_uses_frame_offset_and_affine_matrix() -> None:
    projection = _projection()
    observation = EntityObservation(
        frame="g_1_0",
        pixel_x=400.0,
        pixel_y=300.0,
        identity="lord381757713",
        label="[ROY]lord381757713",
        kind="city",
        level=8,
        confidence=0.9,
        provenance="ocr_projected",
    )

    projected = project_observation(
        observation,
        projection=projection,
        frame_offset=(250.0, 40.0),
        crop_center=(378.0, 537.5),
    )

    expected_pan = (
        1000.0 + 250.0 + (400.0 - 378.0),
        1000.0 + 40.0 + (300.0 - 537.5),
    )
    expected_world = projection.world_from_pixel(*expected_pan)
    assert projected.world_x == pytest.approx(expected_world[0])
    assert projected.world_y == pytest.approx(expected_world[1])
    assert projected.tile_x == round(expected_world[0])
    assert projected.tile_y == round(expected_world[1])
    assert projected.provenance == "ocr_projected"


def test_detect_frame_observations_keeps_ocr_confidence_and_parsed_level() -> None:
    band = np.zeros((240, 320, 3), dtype=np.uint8)
    band[:] = (40, 120, 50)
    # Red circular badge above a city-like structure.
    cv2 = pytest.importorskip("cv2")
    cv2.circle(band, (160, 90), 12, (40, 40, 220), -1)
    cv2.rectangle(band, (140, 100), (180, 150), (90, 90, 90), -1)

    labels = [
        ("8 [ROY]lord381757713", 160.0, 170.0, 0.91),
        ("Alliance Woodmill", 60.0, 50.0, 0.55),
    ]
    observations = detect_frame_observations(
        band,
        frame="c0_center",
        labels_with_confidence=labels,
    )

    city = next(item for item in observations if item.kind == "city")
    mill = next(item for item in observations if item.kind == "mill")
    assert city.identity == "lord381757713"
    assert city.level == 8
    assert city.confidence == pytest.approx(0.91)
    assert city.provenance == "ocr_projected"
    assert mill.identity.startswith("ambig:") or mill.kind == "mill"
    assert mill.level is None


def test_detect_frame_observations_emits_unknown_for_badge_without_label() -> None:
    cv2 = pytest.importorskip("cv2")
    band = np.zeros((240, 320, 3), dtype=np.uint8)
    band[:] = (40, 120, 50)
    cv2.circle(band, (200, 120), 11, (30, 35, 210), -1)
    cv2.rectangle(band, (185, 130), (215, 165), (70, 80, 90), -1)

    observations = detect_frame_observations(
        band,
        frame="g_0_1",
        labels_with_confidence=[],
    )

    unknowns = [item for item in observations if item.kind == "unknown"]
    assert unknowns
    assert all(item.provenance == "visual_projected" for item in unknowns)
    assert all(0.0 < item.confidence <= 1.0 for item in unknowns)


def test_merge_prefers_popup_exact_and_records_provenance() -> None:
    base = dict(
        frame="c0_center",
        pixel_x=100.0,
        pixel_y=100.0,
        identity="lord381757713",
        label="[ROY]lord381757713",
        kind="city",
        level=8,
        world_x=1118.2,
        world_y=286.1,
        tile_x=1118,
        tile_y=286,
        confidence=0.7,
        provenance="ocr_projected",
    )
    ocr = EntityObservation(**base)
    popup = EntityObservation(
        **{
            **base,
            "frame": "g_1_0",
            "world_x": 1118.0,
            "world_y": 286.0,
            "confidence": 0.98,
            "provenance": "popup_exact",
            "popup_path": "popups/g_1_0-1.png",
        }
    )
    visual = EntityObservation(
        frame="g_0_1",
        pixel_x=120.0,
        pixel_y=110.0,
        identity=None,
        label="",
        kind="unknown",
        level=None,
        world_x=1118.3,
        world_y=286.2,
        tile_x=1118,
        tile_y=286,
        confidence=0.4,
        provenance="visual_projected",
    )

    catalog = merge_entity_observations([ocr, popup, visual])

    assert len(catalog) == 1
    entry = catalog[0]
    assert isinstance(entry, EntityCatalogEntry)
    assert entry.provenance == "popup_exact"
    assert entry.world_x == pytest.approx(1118.0)
    assert entry.world_y == pytest.approx(286.0)
    assert entry.confidence >= 0.98
    assert set(entry.source_frames) == {"c0_center", "g_1_0", "g_0_1"}
    assert entry.popup_path == "popups/g_1_0-1.png"
    assert entry.coordinate_residual_px is not None


def test_merge_rejects_same_identity_with_disagreement() -> None:
    a = EntityObservation(
        frame="c0_center",
        pixel_x=10.0,
        pixel_y=10.0,
        identity="lord381757713",
        label="lord381757713",
        kind="city",
        level=8,
        world_x=1118.0,
        world_y=286.0,
        tile_x=1118,
        tile_y=286,
        confidence=0.9,
        provenance="ocr_projected",
    )
    b = EntityObservation(
        frame="g_2_2",
        pixel_x=20.0,
        pixel_y=20.0,
        identity="lord381757713",
        label="lord381757713",
        kind="city",
        level=8,
        world_x=1125.0,
        world_y=295.0,
        tile_x=1125,
        tile_y=295,
        confidence=0.9,
        provenance="ocr_projected",
    )

    with pytest.raises(ValueError, match="coordinate disagreement"):
        merge_entity_observations([a, b], max_world_delta=0.75)
