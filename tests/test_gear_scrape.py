from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np
import pytest

from ks.device.fake import FakeDevice
from ks.heroes.errors import DetailOpenError
from ks.heroes.gear_config import load_gear_config
from ks.heroes.gear_models import GearRecord, make_piece_id
from ks.heroes.gear_scrape import scrape_gear_piece

_IMG_W, _IMG_H = 1080, 1920
_TOP_BOX = (80, 240, min(920, _IMG_W - 80), min(220, _IMG_H - 240))
_BODY_BOX = (80, 300, min(920, _IMG_W - 80), min(500, _IMG_H - 300))


def _png() -> bytes:
    ok, buf = cv2.imencode(".png", np.zeros((_IMG_H, _IMG_W, 3), dtype=np.uint8))
    assert ok
    return buf.tobytes()


def _make_fake_ocr(cfg, *, detail_open: bool = True, blank_fields: bool = False):
    """Fake OCR routing by exact box match, mirroring the live detail-modal layout."""

    def fake_ocr(_image: np.ndarray, box: tuple[int, int, int, int]) -> str:
        if box == _TOP_BOX:
            return "Gear Details" if detail_open else ""
        if box == _BODY_BOX:
            return ""
        if blank_fields:
            return ""
        if cfg.ocr.name is not None and box == cfg.ocr.name.as_tuple():
            return "Stonewall Helm"
        if cfg.ocr.rarity is not None and box == cfg.ocr.rarity.as_tuple():
            return "Mythic"
        if cfg.ocr.power is not None and box == cfg.ocr.power.as_tuple():
            return "12,345"
        if cfg.ocr.enhancement is not None and box == cfg.ocr.enhancement.as_tuple():
            return "+30"
        if cfg.ocr.mastery is not None and box == cfg.ocr.mastery.as_tuple():
            return "Lv. 3"
        if box == cfg.ocr.detail_panel.as_tuple():
            return "Conquest Stats\nHero Attack 1,200"
        return ""

    return fake_ocr


def test_scrape_gear_piece_returns_none_when_detail_not_open():
    cfg = load_gear_config()
    device = FakeDevice(png_bytes=_png())
    ocr = _make_fake_ocr(cfg, detail_open=False)

    assert scrape_gear_piece(device, cfg, page=0, index=0, ocr_fn=ocr) is None


def test_scrape_gear_piece_raises_when_detail_open_but_ocr_empty():
    cfg = load_gear_config()
    device = FakeDevice(png_bytes=_png())
    ocr = _make_fake_ocr(cfg, detail_open=True, blank_fields=True)

    with pytest.raises(DetailOpenError):
        scrape_gear_piece(device, cfg, page=2, index=3, ocr_fn=ocr)


def test_scrape_gear_piece_builds_record_and_saves_screenshot(tmp_path, monkeypatch):
    cfg = load_gear_config()
    device = FakeDevice(png_bytes=_png())
    ocr = _make_fake_ocr(cfg)

    captured: dict[str, str] = {}

    def fake_parse(text: str, *, page: int, index: int) -> GearRecord:
        captured["text"] = text
        return GearRecord(
            piece_id=make_piece_id(page, index),
            name="Stonewall Helm",
            rarity="mythic",
            enhancement_level=30,
            mastery_level=3,
            power=12345,
            inventory_page=page,
            inventory_index=index,
            raw_text=text,
        )

    monkeypatch.setattr("ks.heroes.gear_scrape.parse_gear_detail", fake_parse)

    details_dir = tmp_path / "details"
    piece = scrape_gear_piece(device, cfg, page=1, index=2, ocr_fn=ocr, details_dir=details_dir)

    assert piece is not None
    assert piece.piece_id == "page1-cell2"
    assert piece.name == "Stonewall Helm"
    assert piece.enhancement_level == 30
    assert piece.mastery_level == 3
    assert piece.power == 12345
    assert piece.inventory_page == 1
    assert piece.inventory_index == 2
    assert piece.scraped_at is not None
    assert piece.detail_screenshot == "details/page1-cell2.png"
    assert (details_dir / "page1-cell2.png").is_file()
    # Focused-crop OCR (name/rarity/power/enhancement/mastery) plus the badge
    # and full detail-panel text should all reach the parser.
    assert "Stonewall Helm" in captured["text"]
    assert "+30" in captured["text"]
    assert "Conquest Stats" in captured["text"]


def test_scrape_gear_piece_skips_screenshot_when_disabled(tmp_path, monkeypatch):
    cfg = replace(load_gear_config(), save_screenshots=False)
    device = FakeDevice(png_bytes=_png())
    ocr = _make_fake_ocr(cfg)

    monkeypatch.setattr(
        "ks.heroes.gear_scrape.parse_gear_detail",
        lambda text, *, page, index: GearRecord(
            piece_id=make_piece_id(page, index), inventory_page=page, inventory_index=index, raw_text=text
        ),
    )

    details_dir = tmp_path / "details"
    piece = scrape_gear_piece(device, cfg, page=0, index=0, ocr_fn=ocr, details_dir=details_dir)

    assert piece is not None
    assert piece.detail_screenshot is None
    assert not details_dir.exists()
