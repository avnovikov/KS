"""Tests for sprite template matching."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ks.cartograph.entities import detect_frame_observations
from ks.cartograph.sprites import (
    export_yolo_labels_stub,
    match_sprite_observations,
    match_sprites,
)


def _make_template(color: tuple[int, int, int] = (40, 180, 40)) -> np.ndarray:
    template = np.zeros((40, 40, 3), dtype=np.uint8)
    cv2.circle(template, (20, 20), 14, color, -1)
    cv2.circle(template, (20, 20), 14, (255, 255, 255), 2)
    return template


def test_match_sprites_finds_planted_template() -> None:
    template = _make_template()
    band = np.full((200, 200, 3), 30, dtype=np.uint8)
    band[80:120, 90:130] = template

    hits = match_sprites(
        band,
        templates=[("beast", "wolf_seed", template)],
        scales=(1.0,),
        threshold=0.8,
    )

    assert hits
    assert hits[0].kind == "beast"
    assert abs(hits[0].pixel_x - 110) < 8
    assert abs(hits[0].pixel_y - 100) < 8
    assert hits[0].confidence >= 0.8


def test_detect_frame_observations_includes_sprite_hits() -> None:
    template = _make_template((20, 90, 200))
    band = np.full((160, 160, 3), 25, dtype=np.uint8)
    band[50:90, 60:100] = template

    observations = detect_frame_observations(
        band,
        frame="c0_center",
        labels_with_confidence=(),
        sprite_matcher=lambda band, frame: match_sprite_observations(
            band,
            frame=frame,
            templates=[("rss", "farm_seed", template)],
        ),
    )

    assert any(item.kind == "rss" and item.provenance == "visual_projected" for item in observations)


def test_export_yolo_labels_stub_mentions_graduation() -> None:
    text = export_yolo_labels_stub()
    assert "yolov8n" in text
    assert "beast" in text
