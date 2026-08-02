from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple, Protocol

import cv2
import numpy as np

from ks.heroes.config import HeroesConfig, OcrBox
from ks.heroes.errors import DetailOpenError
from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.name_ocr import resolve_hero_name
from ks.heroes.name_shot import save_name_screenshot
from ks.heroes.ocr_util import ocr_box_robust, region_text_lower, text_has_any
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
    tabs = region_text_lower(
        image, (100, tab_y, min(880, w - 100), min(110, h - tab_y))
    )
    if text_has_any(tabs, ("skill", "gear", "stat")):
        return True
    # Ascend / promotion overlay is still a hero context.
    mid = region_text_lower(
        image,
        (300, min(h - 280, h - 1), 480, 120),
        whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        psm=7,
    )
    return text_has_any(mid, ("ascend", "upgrade", "pgrade"))


def dismiss_blocking_overlays(device: DeviceProtocol, cfg: HeroesConfig, *, sleep_fn) -> np.ndarray:
    """Leave Ascend/promotion overlays so Stats/Skills are reachable."""
    img = _decode_screencap(device.screencap())
    h, w = img.shape[:2]
    for _ in range(3):
        mid = region_text_lower(
            img,
            (300, min(h - 280, h - 1), 480, 120),
            whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            psm=7,
        )
        if not text_has_any(mid, ("ascend", "promotion")):
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


def _detail_screen_image_or_none(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    ocr_fn: OcrFn | None,
    sleep: Callable[[float], None],
):
    """Decode the current screencap; classify it unless ``ocr_fn`` is injected.

    Tests inject ``ocr_fn`` and skip live screen classification entirely.
    Returns the decoded image, or None when the live classifier determines
    this is not an open hero detail screen.
    """
    img = _decode_screencap(device.screencap())
    if ocr_fn is None:
        img = dismiss_blocking_overlays(device, cfg, sleep_fn=sleep)
        if not is_hero_detail_screen(img):
            return None
    return img


class _HeroIdentity(NamedTuple):
    name: str
    power: int | None
    name_screenshot: str | None
    rarity_ui: str | None


def _resolve_hero_name_and_rarity(
    img,
    cfg: HeroesConfig,
    *,
    ocr_fn: OcrFn | None,
    names_dir: Path | None,
) -> tuple[str | None, str, str | None, str | None]:
    """OCR the hero name; also resolves rarity/color on the live vision path.

    Returns (name, raw_name, rarity_ui, color). On the injected-``ocr_fn``
    (test) path, ``rarity_ui``/``color`` are always None since only the name
    box is OCR'd.
    """
    if ocr_fn is not None:
        name = clean_name(ocr_fn(img, cfg.ocr.name.as_tuple()))
        return name, name or "", None, None
    return resolve_hero_name(
        img,
        cfg.ocr.name.as_tuple(),
        rarity_box=cfg.ocr.rarity.as_tuple(),
        templates_dir=names_dir,
    )


def _resolve_missing_name(
    *,
    power: int | None,
    keep_name: str | None,
    ocr_fn: OcrFn | None,
    page: int,
    index: int,
) -> str | None:
    """Resolve a placeholder name when name OCR found nothing.

    Returns None when the caller should treat this as a scrape failure (only
    reachable on the injected-``ocr_fn`` test path). On the live path
    (``ocr_fn`` is None), raises ``DetailOpenError`` in that same situation
    since the detail screen is already confirmed open and the collector still
    needs to tap Back.
    """
    if power is None and not keep_name:
        if ocr_fn is None:
            raise DetailOpenError(
                f"hero detail open but name/power OCR failed "
                f"(page={page} index={index})"
            )
        return None
    name = f"Hero_p{page}_i{index}"
    print(
        f"warn: placeholder hero name {name!r} "
        f"(page={page} index={index}, power={power})"
    )
    return name


def _resolve_hero_identity(
    img,
    cfg: HeroesConfig,
    *,
    ocr_fn: OcrFn | None,
    names_dir: Path | None,
    keep_name: str | None,
    page: int,
    index: int,
) -> _HeroIdentity | None:
    """Resolve name + power for the open detail screen; saves the name screenshot.

    Returns None when both name and power OCR come back empty on an injected
    ``ocr_fn`` (test) path. On the live path (``ocr_fn`` is None) that same
    condition instead raises ``DetailOpenError``, since the detail screen is
    already confirmed open and the collector still needs to tap Back.
    """
    name, raw_name, rarity_ui, color = _resolve_hero_name_and_rarity(
        img, cfg, ocr_fn=ocr_fn, names_dir=names_dir
    )
    digits_fn = ocr_fn or _digits_ocr
    power = parse_power(digits_fn(img, cfg.ocr.power.as_tuple()))
    if name is None:
        name = _resolve_missing_name(
            power=power, keep_name=keep_name, ocr_fn=ocr_fn, page=page, index=index
        )
        if name is None:
            return None
    if keep_name and keep_name.strip():
        name = keep_name.strip()
    if raw_name and name and clean_name(raw_name) != name:
        print(f"name OCR {raw_name!r} → {name} (rarity={rarity_ui} color={color})")

    name_screenshot: str | None = None
    if names_dir is not None:
        name_screenshot = save_name_screenshot(img, cfg.ocr.name, names_dir, name)

    return _HeroIdentity(name=name, power=power, name_screenshot=name_screenshot, rarity_ui=rarity_ui)


class _SecondaryAttributes(NamedTuple):
    rarity: str | None
    escorts: int | None
    troop_type: str | None
    stars: int | None
    pellets: int | None


def _resolve_troop_type(
    img, cfg: HeroesConfig, ocr: OcrFn, name: str, *, used_catalog_name_resolution: bool
) -> str | None:
    """OCR the troop-type box, then prefer the name catalog's troop if known."""
    troop_type = None
    if cfg.ocr.troop_type is not None:
        troop_raw = _ocr_box(img, cfg.ocr.troop_type, ocr).strip()
        troop_type = troop_raw or None
    if used_catalog_name_resolution and name and not name.startswith("Hero_p"):
        from ks.heroes.name_ocr import load_name_catalog

        entry = load_name_catalog().get(name)
        if entry and entry.troop:
            troop_type = entry.troop
    return troop_type


def _scrape_secondary_attributes(
    img,
    cfg: HeroesConfig,
    ocr: OcrFn,
    ocr_fn: OcrFn | None,
    name: str,
    rarity_ui: str | None,
) -> _SecondaryAttributes:
    """OCR rarity, escorts, troop type, and star/pellet progress."""
    rarity = rarity_ui or parse_rarity(_ocr_box(img, cfg.ocr.rarity, ocr))
    escorts = parse_int(_ocr_box(img, cfg.ocr.escorts, ocr))
    # Prefer catalog troop when name resolved from catalog (live path only).
    troop_type = _resolve_troop_type(
        img, cfg, ocr, name, used_catalog_name_resolution=ocr_fn is None
    )
    stars = None
    pellets = None
    if cfg.ocr.stars is not None:
        progress = count_stars_pellets(img, cfg.ocr.stars)
        stars = progress.stars
        pellets = progress.pellets
    return _SecondaryAttributes(
        rarity=rarity, escorts=escorts, troop_type=troop_type, stars=stars, pellets=pellets
    )


def _capture_stats_panel(
    device: DeviceProtocol, cfg: HeroesConfig, ocr: OcrFn, sleep: Callable[[float], None]
):
    """Open the Stats popup, OCR it, and close it again."""
    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
    _sleep_ms(cfg.delays.after_tap_ms, sleep_fn=sleep)
    stats_img = _decode_screencap(device.screencap())
    stats = parse_stats_panel(_ocr_box(stats_img, cfg.ocr.stats_panel, ocr))
    device.tap(cfg.nav.stats_list_button.x, cfg.nav.stats_list_button.y)
    _sleep_ms(cfg.delays.after_tap_ms, sleep_fn=sleep)
    return stats


def _capture_skills(
    device: DeviceProtocol, cfg: HeroesConfig, ocr: OcrFn, sleep: Callable[[float], None]
) -> list[SkillRecord]:
    """Open the Skills tab and OCR each configured skill slot."""
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
    return skills


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
    on_power_breakdown: Callable[[Any], None] | None = None,
) -> HeroRecord | None:
    """Scrape the currently open hero detail screen.

    Caller owns roster open and back navigation.

    Returns None when the detail screen is not open (live path) or when an
    injected ``ocr_fn`` yields no name/power. When the live path confirms a
    detail screen but name and power both fail, raises ``DetailOpenError`` so
    the collector still taps Back.

    When ``keep_name`` is set (manual fix), that name wins over OCR and is used
    for the top-center name screenshot filename. Otherwise a name OCR miss with
    power present yields a placeholder ``Hero_p{page}_i{index}``.
    """
    if page < 0:
        raise ValueError(f"page must be >= 0; got {page}")
    if index < 0:
        raise ValueError(f"index must be >= 0; got {index}")

    ocr = ocr_fn or _default_ocr
    sleep = sleep_fn or time.sleep
    now = now_fn or (lambda: datetime.now(timezone.utc))

    img = _detail_screen_image_or_none(device, cfg, ocr_fn, sleep)
    if img is None:
        return None

    identity = _resolve_hero_identity(
        img, cfg, ocr_fn=ocr_fn, names_dir=names_dir, keep_name=keep_name, page=page, index=index
    )
    if identity is None:
        return None

    attrs = _scrape_secondary_attributes(img, cfg, ocr, ocr_fn, identity.name, identity.rarity_ui)

    # Power-i while still on Stats chrome (before stats popup / Skills tab).
    # Live path only — injected ocr_fn tests skip ADB tooltip capture.
    if on_power_breakdown is not None and ocr_fn is None:
        try:
            from ks.heroes.power_i_capture import capture_power_i_breakdown

            captured = capture_power_i_breakdown(
                device, cfg, sleep_fn=sleep, names_dir=names_dir
            )
            if captured is not None:
                on_power_breakdown(captured)
        except Exception as exc:  # noqa: BLE001 — rescan must continue
            print(f"warn: Power-i capture failed for {identity.name!r}: {exc}")

    stats = _capture_stats_panel(device, cfg, ocr, sleep)
    skills = _capture_skills(device, cfg, ocr, sleep)

    scraped_at = now().isoformat().replace("+00:00", "Z")
    return HeroRecord(
        name=identity.name,
        power=identity.power,
        rarity=attrs.rarity,
        troop_type=attrs.troop_type,
        escorts=attrs.escorts,
        stars=attrs.stars,
        pellets=attrs.pellets,
        stats=stats,
        skills=tuple(skills),
        roster_page=page,
        roster_index=index,
        scraped_at=scraped_at,
        name_screenshot=identity.name_screenshot,
    )
