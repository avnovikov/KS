from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import cv2
import numpy as np

from ks.heroes.config import HeroesConfig, OcrBox
from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.name_ocr import resolve_hero_name
from ks.heroes.name_shot import save_name_screenshot
from ks.heroes.ocr_util import ocr_box_robust
from ks.heroes.parse import (
    clean_name,
    parse_int,
    parse_power,
    parse_rarity,
    parse_skill_panel,
    parse_stats_panel,
)
from ks.heroes.stars_vision import count_stars_pellets
from ks.heroes.teal_ocr import extract_teal_current_percent


def _default_ocr(image: np.ndarray, box: tuple[int, int, int, int]) -> str:
    return ocr_box_robust(image, box, psm=6)


def _digits_ocr(image: np.ndarray, box: tuple[int, int, int, int]) -> str:
    return ocr_box_robust(
        image,
        box,
        whitelist="0123456789,",
        psm=7,
    )


def is_hero_detail_screen(image: np.ndarray) -> bool:
    """True when the screenshot looks like an open hero detail (not roster)."""
    h, w = image.shape[:2]
    # Bottom tabs: Stats / Skills / Gear are unique to detail (1080x1920).
    tab_y = max(0, h - 120)
    tabs = ocr_box_robust(
        image,
        (100, tab_y, min(880, w - 100), min(110, h - tab_y)),
        psm=6,
    ).lower()
    if "skill" in tabs or "gear" in tabs or "stat" in tabs:
        return True
    # Ascend / promotion overlay is still a hero context.
    mid = ocr_box_robust(
        image,
        (300, min(h - 280, h - 1), 480, 120),
        whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        psm=7,
    ).lower()
    if "ascend" in mid or "upgrade" in mid or "pgrade" in mid:
        return True
    return False


def dismiss_blocking_overlays(device: DeviceProtocol, cfg: HeroesConfig, *, sleep_fn) -> np.ndarray:
    """Leave Ascend/promotion overlays so Stats/Skills are reachable."""
    img = _decode_screencap(device.screencap())
    h, w = img.shape[:2]
    for _ in range(3):
        mid = ocr_box_robust(
            img,
            (300, min(h - 280, h - 1), 480, 120),
            whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            psm=7,
        ).lower()
        if "ascend" not in mid and "promotion" not in mid:
            break
        device.tap(cfg.nav.back.x, cfg.nav.back.y)
        _sleep_ms(cfg.delays.after_tap_ms, sleep_fn=sleep_fn)
        img = _decode_screencap(device.screencap())
    return img


OcrFn = Callable[[np.ndarray, tuple[int, int, int, int]], str]


class DeviceProtocol(Protocol):
    def screencap(self) -> bytes: ...

    def tap(self, x: int, y: int) -> None: ...


def decode_screencap(png_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("screencap did not decode as an image")
    return img


# Back-compat alias for internal callers / older imports.
_decode_screencap = decode_screencap


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
    names_dir: Path | None = None,
    keep_name: str | None = None,
) -> HeroRecord | None:
    """Scrape the currently open hero detail screen.

    Caller owns roster open and back navigation. Returns None if name OCR fails.
    When ``keep_name`` is set (manual fix), that name wins over OCR and is used
    for the top-center name screenshot filename.
    """
    if page < 0:
        raise ValueError(f"page must be >= 0; got {page}")
    if index < 0:
        raise ValueError(f"index must be >= 0; got {index}")

    ocr = ocr_fn or _default_ocr
    sleep = sleep_fn or time.sleep
    now = now_fn or (lambda: datetime.now(timezone.utc))

    img = _decode_screencap(device.screencap())
    # Injected ocr_fn (tests) skips live screen classification.
    if ocr_fn is None:
        img = dismiss_blocking_overlays(device, cfg, sleep_fn=sleep)
        if not is_hero_detail_screen(img):
            return None

    name_fn = ocr_fn or None
    rarity_ui: str | None = None
    color: str | None = None
    if name_fn is not None:
        name = clean_name(name_fn(img, cfg.ocr.name.as_tuple()))
        raw_name = name or ""
    else:
        name, raw_name, rarity_ui, color = resolve_hero_name(
            img,
            cfg.ocr.name.as_tuple(),
            rarity_box=cfg.ocr.rarity.as_tuple(),
            templates_dir=names_dir,
        )
    digits_fn = ocr_fn or _digits_ocr
    power = parse_power(digits_fn(img, cfg.ocr.power.as_tuple()))
    if name is None:
        if power is None and not keep_name:
            return None
        name = f"Hero_p{page}_i{index}"
    if keep_name and keep_name.strip():
        name = keep_name.strip()
    if raw_name and name and clean_name(raw_name) != name:
        print(f"name OCR {raw_name!r} → {name} (rarity={rarity_ui} color={color})")

    name_screenshot: str | None = None
    if names_dir is not None:
        name_screenshot = save_name_screenshot(img, cfg.ocr.name, names_dir, name)

    rarity = rarity_ui or parse_rarity(_ocr_box(img, cfg.ocr.rarity, ocr))
    escorts = parse_int(_ocr_box(img, cfg.ocr.escorts, ocr))
    troop_type = None
    if cfg.ocr.troop_type is not None:
        troop_raw = _ocr_box(img, cfg.ocr.troop_type, ocr).strip()
        troop_type = troop_raw or None
    # Prefer catalog troop when name resolved from catalog.
    if name_fn is None and name and not name.startswith("Hero_p"):
        from ks.heroes.name_ocr import load_name_catalog

        entry = load_name_catalog().get(name)
        if entry and entry.troop:
            troop_type = entry.troop
    stars = None
    pellets = None
    if cfg.ocr.stars is not None:
        progress = count_stars_pellets(img, cfg.ocr.stars)
        stars = progress.stars
        pellets = progress.pellets

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
        current_bonus = extract_teal_current_percent(
            skill_img, cfg.ocr.skill_panel.as_tuple()
        )
        skills.append(
            parse_skill_panel(panel_text, slot=slot, current_bonus=current_bonus)
        )

    scraped_at = now().isoformat().replace("+00:00", "Z")
    return HeroRecord(
        name=name,
        power=power,
        rarity=rarity,
        troop_type=troop_type,
        escorts=escorts,
        stars=stars,
        pellets=pellets,
        stats=stats,
        skills=tuple(skills),
        roster_page=page,
        roster_index=index,
        scraped_at=scraped_at,
        name_screenshot=name_screenshot,
    )
