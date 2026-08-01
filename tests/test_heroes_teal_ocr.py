from pathlib import Path

import cv2
import numpy as np
import pytest

from ks.heroes.parse import parse_skill_panel
from ks.heroes.teal_ocr import extract_teal_current_percent, teal_highlight_mask


def test_parse_skill_panel_accepts_current_bonus():
    skill = parse_skill_panel(
        "Rally Flag Lv. 3\nDescription long enough here.\n8%/16%/24%",
        slot=0,
        current_bonus=24.0,
    )
    assert skill.current_bonus == 24.0


def test_parse_skill_panel_rejects_out_of_range_bonus():
    with pytest.raises(ValueError, match="current_bonus"):
        parse_skill_panel("x", slot=0, current_bonus=999.0)


def test_extract_teal_from_synthetic_image():
    img = np.zeros((120, 320, 3), dtype=np.uint8)
    # BGR teal/green highlight similar to in-game current tier
    cv2.putText(
        img,
        "216%",
        (40, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (180, 230, 40),
        4,
        cv2.LINE_AA,
    )
    assert teal_highlight_mask(img).sum() > 0
    value = extract_teal_current_percent(img)
    assert value == 216.0


def test_extract_teal_from_live_skill_fixture():
    path = Path("artifacts/heroes/manual-check/play_skill_0.png")
    if not path.is_file():
        pytest.skip("live skill fixture not present")
    img = cv2.imread(str(path))
    assert img is not None
    # Panel region used during live bring-up
    value = extract_teal_current_percent(img, (60, 1220, 960, 300))
    assert value == 216.0
