"""Viewport OCR for cartograph (search-bar X:Y)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from ks.cartograph.viewport import (
    ocr_search_bar_from_image,
    ocr_viewport_from_image,
    parse_viewport_text,
)

FIXTURE = Path("artifacts/cartograph-live/after-town-world.png")


def test_parse_viewport_text_variants():
    assert parse_viewport_text("#2379 X:1045 Y:113") == (1045, 113)
    assert parse_viewport_text("C OQ. #2379 X:1045 Y:113 Kj") == (1045, 113)
    assert parse_viewport_text("X1098 Y:133") == (1098, 133)
    assert parse_viewport_text("nope") is None


def test_ocr_viewport_from_upper_city_popup():
    image = np.full((1920, 1080, 3), 45, dtype=np.uint8)
    cv2.rectangle(image, (180, 250), (900, 520), (225, 225, 225), -1)
    cv2.putText(
        image,
        "X:1098 Y:133",
        (310, 360),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.7,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )

    coords, raw = ocr_viewport_from_image(image)

    assert coords == (1098, 133), raw


def test_ocr_search_bar_ignores_upper_popup_coordinates():
    image = np.full((1920, 1080, 3), 45, dtype=np.uint8)
    cv2.putText(
        image, "X:1098 Y:133", (300, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3
    )
    cv2.putText(
        image,
        "#2379 X:1045 Y:113",
        (220, 1620),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (255, 255, 255),
        3,
    )

    coords, raw = ocr_search_bar_from_image(image)

    assert coords == (1045, 113), raw


@pytest.mark.skipif(not FIXTURE.is_file(), reason="live capture fixture missing")
def test_ocr_viewport_on_live_world_map():
    img = cv2.imread(str(FIXTURE))
    assert img is not None
    coords, raw = ocr_viewport_from_image(img)
    assert coords == (1045, 113), f"got {coords!r} raw={raw!r}"
