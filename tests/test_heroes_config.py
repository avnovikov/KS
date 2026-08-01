from pathlib import Path

import pytest
import yaml

from ks.heroes.config import default_heroes_yaml_dict, load_heroes_config


def test_load_shipped_heroes_config():
    cfg = load_heroes_config()
    assert len(cfg.roster.cells) == 16
    assert len(cfg.skill_slots) == 6
    assert cfg.ocr.name.w > 0


def test_load_heroes_config_requires_16_cells(tmp_path: Path):
    data = default_heroes_yaml_dict()
    data["roster"]["cells"] = data["roster"]["cells"][:15]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly 16"):
        load_heroes_config(path)


def test_load_heroes_config_requires_stats_panel(tmp_path: Path):
    data = default_heroes_yaml_dict()
    del data["ocr"]["stats_panel"]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="ocr.stats_panel"):
        load_heroes_config(path)
