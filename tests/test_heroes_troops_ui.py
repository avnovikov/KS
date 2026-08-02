"""Tests for troops inventory UI (YAML edit + FastAPI page)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


_SAMPLE = """\
march_capacity: 1000
truegold: 2

infantry:
  3: 10
  6: 100
cavalry:
  1: 5
archers:
  7: 20
"""


def _write_sample(path: Path) -> Path:
    path.write_text(_SAMPLE, encoding="utf-8")
    return path


def test_load_inventory_fills_tiers_1_to_11(tmp_path: Path) -> None:
    from ks.heroes.ui.troops_inventory import load_inventory

    path = _write_sample(tmp_path / "troops.yaml")
    inv = load_inventory(path)
    assert inv["march_capacity"] == 1000
    assert inv["truegold"] == 2
    assert inv["infantry"][3] == 10
    assert inv["infantry"][6] == 100
    assert inv["infantry"][1] == 0
    assert inv["infantry"][11] == 0
    assert list(inv["infantry"].keys()) == list(range(1, 12))
    assert inv["cavalry"][1] == 5
    assert inv["archers"][7] == 20
    assert inv["totals"]["infantry"] == 110


def test_set_count_persists_and_preserves_truegold(tmp_path: Path) -> None:
    from ks.heroes.ui.troops_inventory import load_inventory, set_count

    path = _write_sample(tmp_path / "troops.yaml")
    updated = set_count(path, "infantry", 6, 999)
    assert updated["infantry"][6] == 999
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["truegold"] == 2
    assert raw["infantry"][6] == 999
    assert load_inventory(path)["infantry"][6] == 999


def test_set_march_capacity(tmp_path: Path) -> None:
    from ks.heroes.ui.troops_inventory import set_march_capacity

    path = _write_sample(tmp_path / "troops.yaml")
    updated = set_march_capacity(path, 5555)
    assert updated["march_capacity"] == 5555
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["march_capacity"] == 5555
    assert raw["truegold"] == 2


def test_set_count_rejects_bad_inputs(tmp_path: Path) -> None:
    from ks.heroes.ui.troops_inventory import set_count

    path = _write_sample(tmp_path / "troops.yaml")
    with pytest.raises(KeyError, match="type"):
        set_count(path, "wizards", 1, 1)
    with pytest.raises(KeyError, match="tier"):
        set_count(path, "infantry", 12, 1)
    with pytest.raises(ValueError, match="non-negative"):
        set_count(path, "infantry", 1, -1)


def test_default_troops_path_siblings_gear_yaml() -> None:
    from ks.heroes.gear_config import DEFAULT_GEAR_CONFIG
    from ks.heroes.ui.troops_inventory import DEFAULT_TROOPS_PATH

    assert DEFAULT_TROOPS_PATH.parent == DEFAULT_GEAR_CONFIG.parent
    assert DEFAULT_TROOPS_PATH.name == "troops.yaml"
    assert DEFAULT_TROOPS_PATH.is_file(), (
        f"expected packaged config at {DEFAULT_TROOPS_PATH}"
    )


def test_create_app_enables_troops_tab_with_default_path(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.models import HeroRecord
    from ks.heroes.store import HeroStore
    from ks.heroes.ui.app import create_app
    from ks.heroes.ui.troops_inventory import DEFAULT_TROOPS_PATH

    if not DEFAULT_TROOPS_PATH.is_file():
        pytest.skip("repo config/troops.yaml missing")

    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    HeroStore(heroes_dir).upsert(
        HeroRecord(name="Helga", stars=1, pellets=0, scraped_at="t")
    )
    client = TestClient(create_app(heroes_dir=heroes_dir))
    page = client.get("/heroes")
    assert page.status_code == 200
    assert b'href="/troops"' in page.content
    assert b'title="config/troops.yaml not found"' not in page.content


def test_troop_icon_url_fallback_svg() -> None:
    from ks.heroes.ui.troop_icons import troop_icon_url

    url = troop_icon_url("infantry", 6)
    assert url.startswith("/static/troops/")
    assert "infantry" in url
    assert "t6" in url


def test_fastapi_troops_page_and_patch(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.models import HeroRecord
    from ks.heroes.store import HeroStore
    from ks.heroes.ui.app import create_app

    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    HeroStore(heroes_dir).upsert(
        HeroRecord(name="Helga", stars=1, pellets=0, scraped_at="t")
    )
    troops = _write_sample(tmp_path / "troops.yaml")
    client = TestClient(create_app(heroes_dir=heroes_dir, troops_path=troops))

    page = client.get("/troops")
    assert page.status_code == 200
    assert b"Troops inventory" in page.content
    assert b"infantry" in page.content

    heroes_page = client.get("/heroes")
    assert b'href="/troops"' in heroes_page.content

    listed = client.get("/api/troops").json()
    assert listed["march_capacity"] == 1000
    assert listed["infantry"]["total"] == 110
    tile6 = next(t for t in listed["infantry"]["tiles"] if t["tier"] == 6)
    assert tile6["count"] == 100
    assert tile6["icon_url"].startswith("/static/troops/")

    res = client.patch("/api/troops/infantry/6", json={"count": 42})
    assert res.status_code == 200
    assert res.json()["count"] == 42
    raw = yaml.safe_load(troops.read_text(encoding="utf-8"))
    assert raw["infantry"][6] == 42
    assert raw["truegold"] == 2

    cap = client.patch(
        "/api/troops/march-capacity", json={"march_capacity": 7777}
    )
    assert cap.status_code == 200
    assert cap.json()["march_capacity"] == 7777
    raw = yaml.safe_load(troops.read_text(encoding="utf-8"))
    assert raw["march_capacity"] == 7777

    bad = client.patch("/api/troops/infantry/99", json={"count": 1})
    assert bad.status_code == 404
    neg = client.patch("/api/troops/cavalry/1", json={"count": -3})
    assert neg.status_code == 400
