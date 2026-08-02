from pathlib import Path

import pytest
import yaml

from ks.heroes.gear_config import DEFAULT_GEAR_CONFIG, load_gear_config


def _minimal_gear_yaml() -> dict:
    return {
        "adb": {"serial": "127.0.0.1:5555"},
        "delays_ms": {
            "after_tap": 700,
            "after_open": 1100,
            "after_tab": 900,
            "after_skill": 700,
        },
        "save_screenshots": True,
        "grid": {
            "max_pages": 1,
            "cells": [{"x": 135, "y": 400}, {"x": 405, "y": 400}],
            "page_swipe": {"x1": 540, "y1": 1500, "x2": 540, "y2": 500, "duration_ms": 400},
        },
        "nav": {
            "close_detail": {"x": 990, "y": 290},
            "back": {"x": 55, "y": 95},
        },
        "ocr": {
            "detail_panel": {"x": 80, "y": 240, "w": 920, "h": 1100},
        },
    }


def test_load_shipped_gear_config():
    cfg = load_gear_config()
    assert cfg.adb_serial == "127.0.0.1:5555"
    assert len(cfg.grid.cells) == 24
    assert cfg.grid.max_pages == 1
    assert cfg.ocr.detail_panel.w > 0
    assert cfg.nav.back is not None


def test_load_gear_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_gear_config(tmp_path / "missing.yaml")


def test_load_gear_config_requires_mapping_root(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_gear_config(path)


def test_load_gear_config_requires_grid_cells(tmp_path: Path):
    data = _minimal_gear_yaml()
    data["grid"]["cells"] = []
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="grid.cells"):
        load_gear_config(path)


def test_load_gear_config_optional_ocr_boxes_default_none(tmp_path: Path):
    data = _minimal_gear_yaml()
    path = tmp_path / "minimal.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    cfg = load_gear_config(path)
    assert cfg.ocr.enhancement is None
    assert cfg.ocr.mastery is None
    assert cfg.ocr.name is None
    assert cfg.nav.back.x == 55


def test_load_gear_config_defaults_without_adb_serial(tmp_path: Path):
    data = _minimal_gear_yaml()
    del data["adb"]
    path = tmp_path / "no_adb.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    cfg = load_gear_config(path)
    assert cfg.adb_serial is None


def test_default_gear_config_path_matches_shipped_config():
    assert DEFAULT_GEAR_CONFIG.name == "gear.yaml"
    assert DEFAULT_GEAR_CONFIG.is_file()
