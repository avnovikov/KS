"""Scrape one backpack gear piece via Gear Details OCR."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import cv2
import numpy as np

from ks.heroes.gear_config import GearConfig
from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_parse import parse_gear_detail
from ks.heroes.ocr_util import ocr_box_robust
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


def is_gear_detail_open(image: np.ndarray, *, ocr_fn: OcrFn | None = None) -> bool:
    """True when the Gear Details modal appears to be open."""
    ocr = ocr_fn or _default_ocr
    h, w = image.shape[:2]
    # Title + identity strip (OCR on "Gear Details" alone is unreliable).
    top = ocr(image, (80, 240, min(920, w - 80), min(220, h - 240))).lower()
    compact = top.replace(" ", "").replace("\n", "")
    if "geardetail" in compact:
        return True
    if ("unequip" in top or "nequip" in top) and any(
        r in top for r in ("mythic", "epic", "rare", "gold", "purple")
    ):
        return True
    body = ocr(image, (80, 300, min(920, w - 80), min(500, h - 300))).lower()
    if "conquest" in body or "expedition" in body:
        return True
    if "hero attack" in body or "hero health" in body:
        return True
    return False


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

    # Focused crops first so name/rarity/power beat noisy full-panel OCR.
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
    texts.append(ocr(img, cfg.ocr.detail_panel.as_tuple()))

    combined = "\n".join(t for t in texts if t).strip()
    if not combined:
        return None

    piece = parse_gear_detail(combined, page=page, index=index)
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    detail_shot: str | None = None
    if details_dir is not None and cfg.save_screenshots:
        details_dir.mkdir(parents=True, exist_ok=True)
        out_path = details_dir / f"{piece.piece_id}.png"
        cv2.imwrite(str(out_path), img)
        detail_shot = f"details/{piece.piece_id}.png"

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
