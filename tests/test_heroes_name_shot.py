from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ks.device.fake import FakeDevice
from ks.heroes.config import load_heroes_config
from ks.heroes.name_shot import (
    rename_name_screenshot,
    sanitize_name_filename,
    save_name_screenshot,
)
from ks.heroes.scrape import scrape_hero


def test_sanitize_name_filename():
    assert sanitize_name_filename("Jabel") == "Jabel"
    assert sanitize_name_filename("  A B  ") == "A_B"


def test_save_name_screenshot_uses_hero_name(tmp_path: Path):
    cfg = load_heroes_config()
    img = np.zeros((1920, 1080, 3), dtype=np.uint8)
    img[:, :] = (40, 80, 160)
    rel = save_name_screenshot(img, cfg.ocr.name, tmp_path / "names", "Olive")
    assert rel == "names/Olive.png"
    path = tmp_path / rel
    assert path.is_file()
    crop = cv2.imread(str(path))
    assert crop is not None
    assert crop.shape[0] == cfg.ocr.name.h
    assert crop.shape[1] == cfg.ocr.name.w


def test_rename_name_screenshot_to_manual_name(tmp_path: Path):
    names = tmp_path / "names"
    names.mkdir()
    old = names / "Hero_p1_i14.png"
    old.write_bytes(b"png")
    new_rel = rename_name_screenshot(tmp_path, "names/Hero_p1_i14.png", "Olive")
    assert new_rel == "names/Olive.png"
    assert (tmp_path / "names" / "Olive.png").is_file()
    assert not old.exists()


def test_scrape_hero_saves_name_crop_with_keep_name(tmp_path: Path):
    cfg = load_heroes_config()
    img = np.zeros((1920, 1080, 3), dtype=np.uint8)
    img[cfg.ocr.name.y : cfg.ocr.name.y + cfg.ocr.name.h, :] = (255, 255, 255)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    device = FakeDevice(png_bytes=buf.tobytes())

    def fake_ocr(_image: np.ndarray, box: tuple[int, int, int, int]) -> str:
        if box == cfg.ocr.name.as_tuple():
            return "garbage"
        if box == cfg.ocr.power.as_tuple():
            return "150816"
        return ""

    hero = scrape_hero(
        device,
        cfg,
        page=1,
        index=14,
        ocr_fn=fake_ocr,
        sleep_fn=lambda _s: None,
        names_dir=tmp_path / "names",
        keep_name="Olive",
    )
    assert hero is not None
    assert hero.name == "Olive"
    assert hero.name_screenshot == "names/Olive.png"
    assert (tmp_path / "names" / "Olive.png").is_file()
