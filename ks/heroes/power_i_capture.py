"""Live ADB capture of the Power-i breakdown tooltip on an open hero detail."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ks.heroes.config import HeroesConfig
from ks.heroes.name_ocr import resolve_hero_name
from ks.heroes.ocr_util import ocr_box_robust
from ks.heroes.power_breakdown import (
    BREAKDOWN_BOX,
    PowerBreakdown,
    parse_power_breakdown,
    power_info_tap_from_power_box,
)
from ks.heroes.scrape import DeviceProtocol, decode_screencap


@dataclass(frozen=True)
class PowerICapture:
    """Power-i OCR plus the name visible on the same screenshot."""

    breakdown: PowerBreakdown
    observed_name: str | None
    raw_name: str


def ocr_power_breakdown_image(img) -> PowerBreakdown:
    """OCR Power-i buckets from a full-screen screenshot that shows the tooltip."""
    text = ocr_box_robust(img, BREAKDOWN_BOX, psm=6)
    parsed = parse_power_breakdown(text)
    if parsed.from_level is None and parsed.from_stars is None:
        h, w = img.shape[:2]
        text = ocr_box_robust(img, (80, 700, min(700, w - 80), 700), psm=6)
        parsed = parse_power_breakdown(text)
    return parsed


def capture_power_i_breakdown(
    device: DeviceProtocol,
    cfg: HeroesConfig,
    *,
    sleep_fn: Callable[[float], None],
    names_dir=None,
) -> PowerICapture | None:
    """Tap Power-i on the open detail screen, OCR buckets + on-screen name, dismiss.

    Returns None when OCR yields no Level/Stars lines (tooltip likely missed).
    """
    box = cfg.ocr.power
    info_x, info_y = power_info_tap_from_power_box(
        x=box.x, y=box.y, w=box.w, h=box.h
    )
    device.tap(info_x, info_y)
    sleep_fn(cfg.delays.after_tap_ms / 1000.0)
    tip = decode_screencap(device.screencap())
    breakdown = ocr_power_breakdown_image(tip)
    # Do NOT use name templates here — labeled crops can be wrong after roster
    # drift and would re-attach the keep_name error. Catalog/OCR only.
    _ = names_dir
    observed, raw_name, _, _ = resolve_hero_name(
        tip,
        cfg.ocr.name.as_tuple(),
        rarity_box=cfg.ocr.rarity.as_tuple(),
        templates_dir=None,
    )
    # Dismiss tooltip (retap i).
    device.tap(info_x, info_y)
    sleep_fn(cfg.delays.after_tap_ms / 1000.0)
    if breakdown.from_level is None and breakdown.from_stars is None:
        return None
    return PowerICapture(
        breakdown=breakdown,
        observed_name=observed,
        raw_name=raw_name or "",
    )
