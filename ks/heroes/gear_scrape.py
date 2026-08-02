"""Scrape one backpack gear piece via Gear Details OCR."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import cv2
import numpy as np

from ks.heroes.errors import DetailOpenError
from ks.heroes.gear_config import GearConfig
from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_parse import parse_gear_detail
from ks.heroes.ocr_util import ocr_box_robust, region_text_lower, text_has_any
from ks.heroes.scrape import decode_screencap


class DeviceProtocol(Protocol):
    def screencap(self) -> bytes: ...

    def tap(self, x: int, y: int) -> None: ...

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None: ...


OcrFn = Callable[[np.ndarray, tuple[int, int, int, int]], str]


def _default_ocr(image: np.ndarray, box: tuple[int, int, int, int]) -> str:
    return ocr_box_robust(image, box, psm=6)


def _digits_ocr(image: np.ndarray, box: tuple[int, int, int, int]) -> str:
    return ocr_box_robust(
        image,
        box,
        whitelist="0123456789,+Lv. ",
        psm=7,
    )


def _ocr_detail_enhancement_badge(
    image: np.ndarray,
    *,
    ocr_fn: OcrFn | None = None,
) -> int | None:
    """Read +N from the gear-icon chip on the open Gear Details modal.

    This is the correct detail-phase source for enhancement (tiny orange badge
    on the icon). Expedition ``+N.NN%`` lines must not be used.
    """
    # Icon top-right on 1080×1920 portrait Gear Details.
    boxes = (
        (230, 300, 90, 55),
        (220, 295, 100, 60),
        (240, 305, 80, 50),
        (200, 290, 120, 70),
    )
    ocr = ocr_fn or _digits_ocr
    found: list[int] = []
    for box in boxes:
        try:
            text = ocr(image, box)
        except ValueError:
            continue
        compact = text.replace(" ", "").strip()
        match = re.search(r"\+?\s*(\d{1,3})\b", compact)
        if not match:
            continue
        level = int(match.group(1))
        if 0 <= level <= 200:
            found.append(level)
    if not found:
        return None
    # Prefer two-digit badge values when present (avoids lone "5" from "+51").
    two_digit = [v for v in found if v >= 10]
    return max(two_digit) if two_digit else max(found)


def is_gear_detail_open(image: np.ndarray, *, ocr_fn: OcrFn | None = None) -> bool:
    """True when the Gear Details modal appears to be open."""
    ocr = ocr_fn or _default_ocr
    h, w = image.shape[:2]
    # Title + identity strip (OCR on "Gear Details" alone is unreliable).
    top = region_text_lower(image, (80, 240, min(920, w - 80), min(220, h - 240)), ocr_fn=ocr)
    compact = top.replace(" ", "").replace("\n", "")
    if "geardetail" in compact:
        return True
    if text_has_any(top, ("unequip", "nequip")) and text_has_any(
        top, ("mythic", "epic", "rare", "gold", "purple")
    ):
        return True
    body = region_text_lower(
        image, (80, 300, min(920, w - 80), min(500, h - 300)), ocr_fn=ocr
    )
    if text_has_any(body, ("conquest", "expedition")):
        return True
    if text_has_any(body, ("hero attack", "hero health")):
        return True
    return False


def _ocr_gear_detail_text(
    img: np.ndarray,
    cfg: GearConfig,
    ocr: OcrFn,
    ocr_fn: OcrFn | None,
) -> str:
    """Gather OCR text from the open Gear Details modal.

    Focused crops first so name/rarity/power beat noisy full-panel OCR.
    Enhancement must be read from the detail-modal icon badge (not the
    expedition ``+N.NN%`` line); the full panel text is appended last as a
    fallback source for the parser.
    """
    texts: list[str] = []
    for box, use_digits in (
        (cfg.ocr.name, False),
        (cfg.ocr.rarity, False),
        (cfg.ocr.power, True),
        (cfg.ocr.enhancement, True),
        (cfg.ocr.mastery, True),
    ):
        if box is None:
            continue
        try:
            fn = _digits_ocr if use_digits and ocr_fn is None else ocr
            texts.append(fn(img, box.as_tuple()))
        except ValueError:
            continue
    badge = _ocr_detail_enhancement_badge(img, ocr_fn=ocr_fn)
    if badge is not None:
        texts.insert(0, f"+{badge}")
    texts.append(ocr(img, cfg.ocr.detail_panel.as_tuple()))
    return "\n".join(t for t in texts if t).strip()


def _save_gear_detail_screenshot(
    img: np.ndarray,
    details_dir: Path | None,
    cfg: GearConfig,
    piece_id: str,
) -> str | None:
    """Write the detail-screen PNG under ``details_dir``; returns its relative path."""
    if details_dir is None or not cfg.save_screenshots:
        return None
    details_dir.mkdir(parents=True, exist_ok=True)
    out_path = details_dir / f"{piece_id}.png"
    if not cv2.imwrite(str(out_path), img):
        print(f"warn: failed to write gear detail screenshot {out_path}")
        return None
    return f"details/{piece_id}.png"


def scrape_gear_piece(
    device: DeviceProtocol,
    cfg: GearConfig,
    *,
    page: int,
    index: int,
    ocr_fn: OcrFn | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    details_dir: Path | None = None,
) -> GearRecord | None:
    """OCR the open Gear Details modal. Caller taps the cell and closes afterward."""
    del sleep_fn  # reserved for future settle retries
    ocr = ocr_fn or _default_ocr

    img = decode_screencap(device.screencap())
    if not is_gear_detail_open(img, ocr_fn=ocr):
        return None

    combined = _ocr_gear_detail_text(img, cfg, ocr, ocr_fn)
    if not combined:
        raise DetailOpenError(
            f"gear detail open but OCR empty (page={page} index={index})"
        )

    piece = parse_gear_detail(combined, page=page, index=index)
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    detail_shot = _save_gear_detail_screenshot(img, details_dir, cfg, piece.piece_id)

    return GearRecord(
        piece_id=piece.piece_id,
        name=piece.name,
        troop_type=piece.troop_type,
        slot=piece.slot,
        rarity=piece.rarity,
        enhancement_level=piece.enhancement_level,
        mastery_level=piece.mastery_level,
        power=piece.power,
        equipped=piece.equipped,
        equipped_hero=piece.equipped_hero,
        stats=piece.stats,
        raw_text=piece.raw_text,
        inventory_page=page,
        inventory_index=index,
        scraped_at=scraped_at,
        detail_screenshot=detail_shot,
    )


def close_gear_detail(
    device: DeviceProtocol,
    cfg: GearConfig,
    *,
    sleep_fn: Callable[[float], None] | None = None,
) -> None:
    sleep = sleep_fn or time.sleep
    device.tap(cfg.nav.close_detail.x, cfg.nav.close_detail.y)
    sleep(cfg.delays.after_tap_ms / 1000.0)
