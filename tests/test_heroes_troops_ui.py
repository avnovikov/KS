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


def test_create_app_links_troops_without_a_troops_path(tmp_path: Path) -> None:
    """Troops is reachable from the heroes screen with no `troops_path` given.

    Was `test_create_app_enables_troops_tab_with_default_path`, which pinned
    the old `/heroes` page linking `/troops` and the tab being greyed out when
    `config/troops.yaml` was absent. The /inventory IA has no gated tab: the
    store seeds its own per-install copy, so the subtab is always live. What
    is still worth pinning — and is what that test was really about — is that
    the default (no-argument) app links the troops screen rather than
    stranding it.
    """
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
    client = TestClient(create_app(heroes_dir=heroes_dir))
    page = client.get("/inventory/heroes")
    assert page.status_code == 200
    assert b'href="/inventory/troops"' in page.content
    # Seeded next to the roster, from the packaged config.
    assert (heroes_dir / "troops.yaml").is_file()


def test_troop_icon_url_fallback_svg() -> None:
    from ks.heroes.ui.troop_icons import troop_icon_url

    url = troop_icon_url("infantry", 6)
    assert url.startswith("/static/troops/")
    assert "infantry" in url
    assert "t6" in url


def test_fastapi_troops_page_and_put(tmp_path: Path) -> None:
    """`troops_path` points the whole troops screen at an existing document.

    Was `test_fastapi_troops_page_and_patch`. The `/troops` page and the
    granular `PATCH /api/troops/march-capacity` and
    `PATCH /api/troops/{type}/{tier}` endpoints it exercised are not part of
    the /inventory IA; `/inventory/troops` plus whole-document
    `GET`/`PUT /api/troops` supersede them. What survives from the original
    is the part that is not IA: passing `troops_path` must make that file —
    not a freshly seeded one next to the roster — the file the screen reads
    and the file an edit lands in.
    """
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

    page = client.get("/inventory/troops")
    assert page.status_code == 200
    assert b"Troops" in page.content
    assert b"infantry" in page.content
    # The override wins: nothing was seeded beside the roster.
    assert not (heroes_dir / "troops.yaml").exists()

    listed = client.get("/api/troops").json()
    assert listed["troops"]["march_capacity"] == 1000
    assert listed["troops"]["truegold"] == 2
    assert listed["totals"]["infantry"] == 110

    # Tier keys come back over JSON as strings — JSON has no integer keys —
    # and go back the same way; the store's loader accepts either.
    body = dict(listed["troops"])
    body["march_capacity"] = 7777
    body["infantry"] = {**body["infantry"], "6": 42}
    res = client.put("/api/troops", json=body)
    assert res.status_code == 200
    assert res.json()["troops"]["march_capacity"] == 7777
    assert res.json()["totals"]["infantry"] == 52

    raw = yaml.safe_load(troops.read_text(encoding="utf-8"))
    assert raw["march_capacity"] == 7777
    assert int(raw["infantry"]["6"]) == 42
    assert raw["truegold"] == 2

    neg = client.put("/api/troops", json={**body, "march_capacity": -3})
    assert neg.status_code == 422
