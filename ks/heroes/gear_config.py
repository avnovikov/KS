"""Load config/gear.yaml for backpack gear inventory collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.config import DelaysConfig, OcrBox, PageSwipe, TapPoint, _box, _tap

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GEAR_CONFIG = _PROJECT_ROOT / "config" / "gear.yaml"


@dataclass(frozen=True)
class GearGridConfig:
    cells: tuple[TapPoint, ...]
    page_swipe: PageSwipe
    max_pages: int = 20


@dataclass(frozen=True)
class GearNavConfig:
    close_detail: TapPoint
    back: TapPoint | None = None


@dataclass(frozen=True)
class GearOcrRegions:
    detail_panel: OcrBox
    enhancement: OcrBox | None = None
    mastery: OcrBox | None = None
    name: OcrBox | None = None
    rarity: OcrBox | None = None
    power: OcrBox | None = None


@dataclass(frozen=True)
class GearConfig:
    adb_serial: str | None
    delays: DelaysConfig
    grid: GearGridConfig
    nav: GearNavConfig
    ocr: GearOcrRegions
    save_screenshots: bool = True


def _optional_box(raw: Any, *, label: str) -> OcrBox | None:
    if raw is None:
        return None
    return _box(raw, label=label)


def _optional_tap(raw: Any, *, label: str) -> TapPoint | None:
    if raw is None:
        return None
    return _tap(raw, label=label)


def load_gear_config(path: Path | None = None) -> GearConfig:
    config_path = path if path is not None else DEFAULT_GEAR_CONFIG
    if not config_path.is_file():
        raise FileNotFoundError(f"gear config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("gear config root must be a mapping")

    adb = raw.get("adb") or {}
    serial = adb.get("serial") if isinstance(adb, dict) else None

    delays_raw = raw.get("delays_ms") or {}
    if not isinstance(delays_raw, dict):
        raise ValueError("delays_ms must be a mapping")
    delays = DelaysConfig(
        after_tap_ms=int(delays_raw.get("after_tap", 700)),
        after_open_ms=int(delays_raw.get("after_open", 1100)),
        after_tab_ms=int(delays_raw.get("after_tab", 900)),
        after_skill_ms=int(delays_raw.get("after_skill", 700)),
    )

    grid_raw = raw.get("grid") or {}
    if not isinstance(grid_raw, dict):
        raise ValueError("grid must be a mapping")
    cells_raw = grid_raw.get("cells")
    if not isinstance(cells_raw, list) or not cells_raw:
        raise ValueError("grid.cells must be a non-empty list")
    cells = tuple(_tap(c, label=f"grid.cells[{i}]") for i, c in enumerate(cells_raw))
    swipe_raw = grid_raw.get("page_swipe") or {}
    if not isinstance(swipe_raw, dict):
        raise ValueError("grid.page_swipe must be a mapping")
    page_swipe = PageSwipe(
        x1=int(swipe_raw["x1"]),
        y1=int(swipe_raw["y1"]),
        x2=int(swipe_raw["x2"]),
        y2=int(swipe_raw["y2"]),
        duration_ms=int(swipe_raw.get("duration_ms", 400)),
    )
    grid = GearGridConfig(
        cells=cells,
        page_swipe=page_swipe,
        max_pages=int(grid_raw.get("max_pages", 20)),
    )

    nav_raw = raw.get("nav") or {}
    if not isinstance(nav_raw, dict):
        raise ValueError("nav must be a mapping")
    nav = GearNavConfig(
        close_detail=_tap(nav_raw.get("close_detail"), label="nav.close_detail"),
        back=_optional_tap(nav_raw.get("back"), label="nav.back"),
    )

    ocr_raw = raw.get("ocr") or {}
    if not isinstance(ocr_raw, dict):
        raise ValueError("ocr must be a mapping")
    ocr = GearOcrRegions(
        detail_panel=_box(ocr_raw.get("detail_panel"), label="ocr.detail_panel"),
        enhancement=_optional_box(ocr_raw.get("enhancement"), label="ocr.enhancement"),
        mastery=_optional_box(ocr_raw.get("mastery"), label="ocr.mastery"),
        name=_optional_box(ocr_raw.get("name"), label="ocr.name"),
        rarity=_optional_box(ocr_raw.get("rarity"), label="ocr.rarity"),
        power=_optional_box(ocr_raw.get("power"), label="ocr.power"),
    )

    return GearConfig(
        adb_serial=str(serial) if serial else None,
        delays=delays,
        grid=grid,
        nav=nav,
        ocr=ocr,
        save_screenshots=bool(raw.get("save_screenshots", True)),
    )
