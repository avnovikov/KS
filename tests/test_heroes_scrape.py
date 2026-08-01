from __future__ import annotations

import cv2
import numpy as np

from ks.device.fake import FakeDevice
from ks.heroes.config import load_heroes_config
from ks.heroes.scrape import scrape_hero


def _png_bytes(width: int = 1080, height: int = 1920) -> bytes:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def test_scrape_hero_tap_order_and_fields():
    cfg = load_heroes_config()
    device = FakeDevice(png_bytes=_png_bytes())

    boxes_seen: list[tuple[int, int, int, int]] = []

    def fake_ocr(image: np.ndarray, box: tuple[int, int, int, int]) -> str:
        boxes_seen.append(box)
        if box == cfg.ocr.name.as_tuple():
            return "Jabel"
        if box == cfg.ocr.power.as_tuple():
            return "1,234,567"
        if box == cfg.ocr.rarity.as_tuple():
            return "SSR"
        if box == cfg.ocr.escorts.as_tuple():
            return "Escorts\n8"
        if cfg.ocr.troop_type and box == cfg.ocr.troop_type.as_tuple():
            return "Cavalry"
        if cfg.ocr.stars and box == cfg.ocr.stars.as_tuple():
            return "1"
        if box == cfg.ocr.stats_panel.as_tuple():
            return "Hero Attack 1,619\nExpedition\nCavalry Attack +101.37%"
        if box == cfg.ocr.skill_panel.as_tuple():
            # First skill slot returns content; later slots repeat → skipped
            if len([t for t in device.taps if t == (cfg.skill_slots[0].x, cfg.skill_slots[0].y)]) <= 1:
                return "Rally Flag Lv. 3\nDescription long enough here.\n8%/16%/24%"
            return "Rally Flag Lv. 3\nDescription long enough here.\n8%/16%/24%"
        return ""

    hero = scrape_hero(
        device,
        cfg,
        page=0,
        index=3,
        ocr_fn=fake_ocr,
        sleep_fn=lambda _s: None,
        names_dir=None,
    )
    assert hero is not None
    assert hero.name == "Jabel"
    assert hero.power == 1_234_567
    assert hero.rarity == "SSR"
    assert hero.escorts == 8
    assert hero.stats is not None
    assert hero.stats.conquest["Hero Attack"] == 1619
    assert len(hero.skills) == 1
    assert hero.skills[0].name == "Rally Flag"
    assert hero.name_screenshot is None

    list_btn = (cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
    skills_tab = (cfg.nav.skills_tab.x, cfg.nav.skills_tab.y)
    assert device.taps[0] == list_btn
    assert device.taps[1] == list_btn
    assert device.taps[2] == skills_tab
    for i, slot in enumerate(cfg.skill_slots):
        assert device.taps[3 + i] == (slot.x, slot.y)


def test_scrape_hero_returns_none_without_name():
    cfg = load_heroes_config()
    device = FakeDevice(png_bytes=_png_bytes())

    def blank_ocr(_image: np.ndarray, _box: tuple[int, int, int, int]) -> str:
        return ""

    assert (
        scrape_hero(
            device,
            cfg,
            page=0,
            index=0,
            ocr_fn=blank_ocr,
            sleep_fn=lambda _s: None,
        )
        is None
    )
    assert device.taps == []
