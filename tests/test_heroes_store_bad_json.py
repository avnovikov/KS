"""HeroStore / GearStore refuse bad JSON shapes instead of wiping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ks.heroes.gear_store import GearStore
from ks.heroes.store import HeroStore


def test_hero_store_rejects_non_list_heroes(tmp_path: Path) -> None:
    path = tmp_path / "heroes.json"
    path.write_text(json.dumps({"heroes": {"Howard": {}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to load"):
        HeroStore(tmp_path)


def test_gear_store_rejects_non_list_gear(tmp_path: Path) -> None:
    path = tmp_path / "gear.json"
    path.write_text(json.dumps({"gear": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to load"):
        GearStore(tmp_path)
