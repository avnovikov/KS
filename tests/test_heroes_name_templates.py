from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ks.heroes.name_templates import (
    load_name_templates,
    match_name_template,
    train_name_ocr_from_crops,
)


def _write_name_crop(path: Path, text_rows: int = 40) -> None:
    """Synthetic white-on-teal crop with a bright letter-like blob."""
    img = np.full((64, 480, 3), (120, 100, 60), dtype=np.uint8)
    # Bright rectangle as stand-in for outlined name glyphs.
    img[12:52, 160:320] = (255, 255, 255)
    cv2.imwrite(str(path), img)


def test_template_self_match(tmp_path: Path):
    names = tmp_path / "names"
    names.mkdir()
    _write_name_crop(names / "Jabel.png")
    templates = load_name_templates(names)
    assert len(templates) == 1
    assert templates[0].name == "Jabel"

    canvas = np.full((1920, 1080, 3), (120, 100, 60), dtype=np.uint8)
    crop = cv2.imread(str(names / "Jabel.png"))
    canvas[26:90, 300:780] = crop
    name, score = match_name_template(canvas, (300, 26, 480, 64), templates)
    assert name == "Jabel"
    assert score > 0.9


def test_train_report_writes_json(tmp_path: Path):
    names = tmp_path / "names"
    names.mkdir()
    _write_name_crop(names / "Diana.png")
    report = train_name_ocr_from_crops(names, labels={"Diana": "Diana"})
    assert report["total"] == 1
    assert (names / "ocr_train_report.json").is_file()
    assert report["template_self"] == 1
