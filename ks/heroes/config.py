from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HEROES_CONFIG = _PROJECT_ROOT / "config" / "heroes.yaml"


@dataclass(frozen=True)
class TapPoint:
    x: int
    y: int


@dataclass(frozen=True)
class OcrBox:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class PageSwipe:
    x1: int
    y1: int
    x2: int
    y2: int
    duration_ms: int = 300


@dataclass(frozen=True)
class DelaysConfig:
    after_tap_ms: int = 400
    after_open_ms: int = 800
    after_tab_ms: int = 600
    after_skill_ms: int = 500


@dataclass(frozen=True)
class RosterConfig:
    cells: tuple[TapPoint, ...]
    page_swipe: PageSwipe
    max_pages: int = 20


@dataclass(frozen=True)
class NavConfig:
    back: TapPoint
    stats_tab: TapPoint
    skills_tab: TapPoint
    stats_list_button: TapPoint


@dataclass(frozen=True)
class OcrRegions:
    name: OcrBox
    power: OcrBox
    rarity: OcrBox
    escorts: OcrBox
    stats_panel: OcrBox
    skill_panel: OcrBox
    troop_type: OcrBox | None = None
    stars: OcrBox | None = None


@dataclass(frozen=True)
class HeroesConfig:
    adb_serial: str | None
    delays: DelaysConfig
    roster: RosterConfig
    nav: NavConfig
    skill_slots: tuple[TapPoint, ...]
    ocr: OcrRegions


def _tap(raw: Any, *, label: str) -> TapPoint:
    if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
        raise ValueError(f"{label} must be a mapping with x and y")
    return TapPoint(x=int(raw["x"]), y=int(raw["y"]))


def _box(raw: Any, *, label: str) -> OcrBox:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping with x,y,w,h")
    for key in ("x", "y", "w", "h"):
        if key not in raw:
            raise ValueError(f"{label} missing {key}")
    box = OcrBox(x=int(raw["x"]), y=int(raw["y"]), w=int(raw["w"]), h=int(raw["h"]))
    if box.w <= 0 or box.h <= 0:
        raise ValueError(f"{label} w and h must be > 0; got {box}")
    return box


def _optional_box(raw: Any, *, label: str) -> OcrBox | None:
    if raw is None:
        return None
    return _box(raw, label=label)


def _parse_delays(raw: dict[str, Any]) -> DelaysConfig:
    delays_raw = raw.get("delays_ms") or {}
    if not isinstance(delays_raw, dict):
        raise ValueError("delays_ms must be a mapping")
    return DelaysConfig(
        after_tap_ms=int(delays_raw.get("after_tap", 400)),
        after_open_ms=int(delays_raw.get("after_open", 800)),
        after_tab_ms=int(delays_raw.get("after_tab", 600)),
        after_skill_ms=int(delays_raw.get("after_skill", 500)),
    )


def _parse_page_swipe(swipe_raw: Any) -> PageSwipe:
    if not isinstance(swipe_raw, dict):
        raise ValueError("roster.page_swipe must be a mapping")
    for key in ("x1", "y1", "x2", "y2"):
        if key not in swipe_raw:
            raise ValueError(f"roster.page_swipe missing {key}")
    return PageSwipe(
        x1=int(swipe_raw["x1"]),
        y1=int(swipe_raw["y1"]),
        x2=int(swipe_raw["x2"]),
        y2=int(swipe_raw["y2"]),
        duration_ms=int(swipe_raw.get("duration_ms", 300)),
    )


def _parse_roster(raw: dict[str, Any]) -> RosterConfig:
    roster_raw = raw.get("roster")
    if not isinstance(roster_raw, dict):
        raise ValueError("roster must be a mapping")
    cells_raw = roster_raw.get("cells") or []
    if not isinstance(cells_raw, list) or len(cells_raw) != 16:
        got = (
            len(cells_raw)
            if isinstance(cells_raw, list)
            else type(cells_raw).__name__
        )
        raise ValueError(f"roster.cells must contain exactly 16 taps; got {got}")
    cells = tuple(
        _tap(c, label=f"roster.cells[{i}]") for i, c in enumerate(cells_raw)
    )
    max_pages = int(roster_raw.get("max_pages", 20))
    if max_pages < 1:
        raise ValueError(f"roster.max_pages must be >= 1; got {max_pages}")
    return RosterConfig(
        cells=cells,
        page_swipe=_parse_page_swipe(roster_raw.get("page_swipe")),
        max_pages=max_pages,
    )


def _parse_nav(raw: dict[str, Any]) -> NavConfig:
    nav_raw = raw.get("nav")
    if not isinstance(nav_raw, dict):
        raise ValueError("nav must be a mapping")
    return NavConfig(
        back=_tap(nav_raw.get("back"), label="nav.back"),
        stats_tab=_tap(nav_raw.get("stats_tab"), label="nav.stats_tab"),
        skills_tab=_tap(nav_raw.get("skills_tab"), label="nav.skills_tab"),
        stats_list_button=_tap(
            nav_raw.get("stats_list_button"), label="nav.stats_list_button"
        ),
    )


def _parse_skill_slots(raw: dict[str, Any]) -> tuple[TapPoint, ...]:
    skills_raw = raw.get("skills") or {}
    if not isinstance(skills_raw, dict):
        raise ValueError("skills must be a mapping")
    slots_raw = skills_raw.get("slots") or []
    if not isinstance(slots_raw, list) or len(slots_raw) < 1:
        raise ValueError("skills.slots must be a non-empty list")
    return tuple(
        _tap(s, label=f"skills.slots[{i}]") for i, s in enumerate(slots_raw)
    )


def _parse_ocr_regions(raw: dict[str, Any]) -> OcrRegions:
    ocr_raw = raw.get("ocr")
    if not isinstance(ocr_raw, dict):
        raise ValueError("ocr must be a mapping")
    required = (
        "name",
        "power",
        "rarity",
        "escorts",
        "stats_panel",
        "skill_panel",
    )
    for key in required:
        if key not in ocr_raw:
            raise ValueError(f"ocr.{key} is required")
    return OcrRegions(
        name=_box(ocr_raw["name"], label="ocr.name"),
        power=_box(ocr_raw["power"], label="ocr.power"),
        rarity=_box(ocr_raw["rarity"], label="ocr.rarity"),
        escorts=_box(ocr_raw["escorts"], label="ocr.escorts"),
        stats_panel=_box(ocr_raw["stats_panel"], label="ocr.stats_panel"),
        skill_panel=_box(ocr_raw["skill_panel"], label="ocr.skill_panel"),
        troop_type=_optional_box(
            ocr_raw.get("troop_type"), label="ocr.troop_type"
        ),
        stars=_optional_box(ocr_raw.get("stars"), label="ocr.stars"),
    )


def load_heroes_config(path: Path | None = None) -> HeroesConfig:
    config_path = path if path is not None else DEFAULT_HEROES_CONFIG
    if not config_path.is_file():
        raise FileNotFoundError(f"heroes config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("heroes config root must be a mapping")

    adb = raw.get("adb") or {}
    serial = adb.get("serial") if isinstance(adb, dict) else None
    return HeroesConfig(
        adb_serial=str(serial) if serial else None,
        delays=_parse_delays(raw),
        roster=_parse_roster(raw),
        nav=_parse_nav(raw),
        skill_slots=_parse_skill_slots(raw),
        ocr=_parse_ocr_regions(raw),
    )


def _grid_cells() -> list[dict[str, int]]:
    """Placeholder 4×4 centers for 1080×1920 portrait."""
    xs = [200, 440, 680, 920]
    ys = [420, 700, 980, 1260]
    return [{"x": x, "y": y} for y in ys for x in xs]


def default_heroes_yaml_dict() -> dict[str, Any]:
    """Sample config used by tests and shipped as config/heroes.yaml."""
    return {
        "adb": {"serial": "127.0.0.1:5555"},
        "delays_ms": {
            "after_tap": 400,
            "after_open": 800,
            "after_tab": 600,
            "after_skill": 500,
        },
        "roster": {
            "max_pages": 20,
            "cells": _grid_cells(),
            "page_swipe": {
                "x1": 900,
                "y1": 900,
                "x2": 200,
                "y2": 900,
                "duration_ms": 350,
            },
        },
        "nav": {
            "back": {"x": 70, "y": 120},
            "stats_tab": {"x": 270, "y": 1850},
            "skills_tab": {"x": 540, "y": 1850},
            "stats_list_button": {"x": 980, "y": 1680},
        },
        "skills": {
            "slots": [
                {"x": 160, "y": 520},
                {"x": 160, "y": 720},
                {"x": 160, "y": 920},
                {"x": 920, "y": 520},
                {"x": 920, "y": 720},
                {"x": 920, "y": 920},
            ]
        },
        "ocr": {
            "name": {"x": 300, "y": 90, "w": 480, "h": 70},
            "power": {"x": 300, "y": 160, "w": 480, "h": 50},
            "rarity": {"x": 40, "y": 100, "w": 160, "h": 80},
            "troop_type": {"x": 400, "y": 210, "w": 280, "h": 40},
            "escorts": {"x": 80, "y": 1550, "w": 200, "h": 60},
            "stars": {"x": 480, "y": 1480, "w": 120, "h": 50},
            "stats_panel": {"x": 520, "y": 520, "w": 500, "h": 700},
            "skill_panel": {"x": 60, "y": 1220, "w": 960, "h": 300},
        },
    }
