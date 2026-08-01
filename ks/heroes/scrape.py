from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Protocol

import cv2
import numpy as np

from ks.heroes.config import HeroesConfig, OcrBox
from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.parse import (
    clean_name,
    parse_int,
    parse_power,
    parse_rarity,
    parse_skill_panel,
    parse_stats_panel,
)
from ks.vision.ocr import ocr_region

OcrFn = Callable[[np.ndarray, tuple[int, int, int, int]], str]


class DeviceProtocol(Protocol):
    def screencap(self) -> bytes: ...

    def tap(self, x: int, y: int) -> None: ...


def _decode_screencap(png_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("screencap did not decode as an image")
    return img


def _ocr_box(img: np.ndarray, box: OcrBox, ocr_fn: OcrFn) -> str:
    return ocr_fn(img, box.as_tuple())


def _sleep_ms(ms: int, *, sleep_fn: Callable[[float], None]) -> None:
    if ms > 0:
        sleep_fn(ms / 1000.0)


def scrape_hero(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    *,
    page: int,
    index: int,
    ocr_fn: OcrFn | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> HeroRecord | None:
    """Scrape the currently open hero detail screen.

    Caller owns roster open and back navigation. Returns None if name OCR fails.
    """
    if page < 0:
        raise ValueError(f"page must be >= 0; got {page}")
    if index < 0:
        raise ValueError(f"index must be >= 0; got {index}")

    ocr = ocr_fn or ocr_region
    sleep = sleep_fn or time.sleep
    now = now_fn or (lambda: datetime.now(timezone.utc))

    img = _decode_screencap(device.screencap())
    name = clean_name(_ocr_box(img, cfg.ocr.name, ocr))
    if name is None:
        return None

    power = parse_power(_ocr_box(img, cfg.ocr.power, ocr))
    rarity = parse_rarity(_ocr_box(img, cfg.ocr.rarity, ocr))
    escorts = parse_int(_ocr_box(img, cfg.ocr.escorts, ocr))
    troop_type = None
    if cfg.ocr.troop_type is not None:
        troop_raw = _ocr_box(img, cfg.ocr.troop_type, ocr).strip()
        troop_type = troop_raw or None
    stars = None
    if cfg.ocr.stars is not None:
        stars = parse_int(_ocr_box(img, cfg.ocr.stars, ocr))

    # Stats popup: open → OCR → close
    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
    _sleep_ms(cfg.delays.after_tap_ms, sleep_fn=sleep)
    stats_img = _decode_screencap(device.screencap())
    stats = parse_stats_panel(_ocr_box(stats_img, cfg.ocr.stats_panel, ocr))
    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
    _sleep_ms(cfg.delays.after_tap_ms, sleep_fn=sleep)

    # Skills tab
    device.tap(cfg.nav.skills_tab.x, cfg.nav.skills_tab.y)
    _sleep_ms(cfg.delays.after_tab_ms, sleep_fn=sleep)

    skills: list[SkillRecord] = []
    previous_panel = ""
    for slot, point in enumerate(cfg.skill_slots):
        device.tap(point.x, point.y)
        _sleep_ms(cfg.delays.after_skill_ms, sleep_fn=sleep)
        skill_img = _decode_screencap(device.screencap())
        panel_text = _ocr_box(skill_img, cfg.ocr.skill_panel, ocr).strip()
        if not panel_text or panel_text == previous_panel:
            continue
        previous_panel = panel_text
        skills.append(parse_skill_panel(panel_text, slot=slot))

    scraped_at = now().isoformat().replace("+00:00", "Z")
    return HeroRecord(
        name=name,
        power=power,
        rarity=rarity,
        troop_type=troop_type,
        escorts=escorts,
        stars=stars,
        stats=stats,
        skills=tuple(skills),
        roster_page=page,
        roster_index=index,
        scraped_at=scraped_at,
    )
