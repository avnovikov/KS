from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ks.heroes.config import OcrBox, load_heroes_config
from ks.heroes.stars_vision import count_stars_pellets


def test_diana_stars_from_fixture():
    path = Path("artifacts/heroes/full-run/diana_stars_now.png")
    if not path.is_file():
        # Skip when fixture absent (CI without artifacts).
        return
    img = cv2.imread(str(path))
    assert img is not None
    cfg = load_heroes_config()
    assert cfg.ocr.stars is not None
    progress = count_stars_pellets(img, cfg.ocr.stars)
    assert progress.stars == 3, progress
    assert progress.pellets == 3, progress
    assert progress.per_slot[0] == 6
    assert progress.per_slot[4] == 0


def test_empty_strip_is_zero_stars():
    img = np.full((1920, 1080, 3), (80, 60, 40), dtype=np.uint8)
    progress = count_stars_pellets(img, OcrBox(x=300, y=1270, w=520, h=85))
    assert progress.stars == 0
    assert progress.pellets == 0
