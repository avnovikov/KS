"""Tests for cartograph label OCR with confidence."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from ks.cartograph.labels import (
    extract_labels,
    extract_labels_with_confidence,
    infer_kind,
    normalize_ocr_label,
    preprocess_label_band,
)
from ks.cartograph.models import FOOTPRINTS, footprint_for


def _city_banner_image(text: str = "8 [ROY]lord385755050") -> np.ndarray:
    image = np.full((120, 420, 3), 40, dtype=np.uint8)
    cv2.putText(
        image,
        text,
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def test_preprocess_label_band_returns_upscaled_gray() -> None:
    band = np.full((60, 80, 3), 50, dtype=np.uint8)
    gray = preprocess_label_band(band, scale=3.0)
    assert gray.ndim == 2
    assert gray.shape[0] == 180
    assert gray.shape[1] == 240


def test_extract_labels_with_confidence_returns_four_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ks.cartograph import labels as labels_module

    def fake_data(*args, **kwargs):
        return {
            "text": ["8", "[ROY]lord123456", "", "noise"],
            "conf": ["88", "91", "-1", "20"],
            "block_num": [1, 1, 1, 2],
            "par_num": [1, 1, 1, 1],
            "line_num": [1, 1, 1, 1],
            "left": [10, 40, 0, 0],
            "top": [10, 10, 0, 0],
            "width": [20, 80, 0, 0],
            "height": [16, 16, 0, 0],
        }

    class FakeTess:
        class Output:
            DICT = "dict"

        @staticmethod
        def image_to_data(image, output_type=None, config=""):
            return fake_data()

    monkeypatch.setattr(labels_module, "tesseract_cmd", lambda: None)
    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakeTess)

    boxes = extract_labels_with_confidence(_city_banner_image())
    assert boxes
    label, px, py, conf = boxes[0]
    assert infer_kind(label) == "city"
    assert 0.0 < conf <= 1.0
    assert px > 0 and py > 0

    legacy = extract_labels(_city_banner_image())
    assert legacy[0][0] == label


@pytest.mark.parametrize(
    ("raw", "kind", "size"),
    [
        ("Alliance Woodmill", "mill", (2, 2)),
        ("All1ance Wooami", "mill", (2, 2)),
        ("Alliance Quarry", "building", (2, 2)),
        ("Alliance Quarny", "building", (2, 2)),
        ("Alliance Iron Mine", "building", (2, 2)),
        ("Alliance Banner", "banner", (2, 2)),
        ("8 [ROY]lord123", "city", (2, 2)),
        ("Plains HQ", "hq", (5, 5)),
        ("Hunting Trap 2", "trap", (3, 3)),
    ],
)
def test_normalize_and_footprint_for_named_structures(
    raw: str, kind: str, size: tuple[int, int]
) -> None:
    cleaned = normalize_ocr_label(raw)
    assert infer_kind(cleaned) == kind
    assert footprint_for(kind, cleaned) == size


def test_resource_and_beast_footprints_are_one_by_one() -> None:
    for kind in ("rss", "beast", "wood", "bread", "stone", "iron"):
        assert FOOTPRINTS[kind] == (1, 1)


@pytest.mark.parametrize(
    "raw",
    [
        "23 [79]Y:287",
        "1 [20]5K",
        "3 [00]:12:10",
        "1 [09]512",
        "0 [PRS]: 0.0",
    ],
)
def test_ui_chrome_is_not_inferred_as_city(raw: str) -> None:
    assert infer_kind(raw) is None
    assert infer_kind(normalize_ocr_label(raw)) is None
