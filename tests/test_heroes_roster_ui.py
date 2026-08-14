"""Tests for heroes roster UI (stars/pellets + star-scaled power)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import star_progress_factor
from ks.heroes.store import HeroStore


def _seed(tmp_path: Path) -> HeroStore:
    store = HeroStore(tmp_path)
    store.upsert(
        HeroRecord(
            name="Helga",
            power=1_000_000,
            troop_type="infantry",
            rarity="legendary",
            stars=2,
            pellets=0,
            roster_page=0,
            roster_index=0,
            scraped_at="2026-08-02T00:00:00Z",
        )
    )
    return store


def test_scale_power_uses_star_progress_ratio() -> None:
    from ks.heroes.ui.hero_power import scale_power_for_star_change

    old_s, old_p, new_s, new_p = 2, 0, 3, 0
    power = 1_000_000
    expected = round(
        power
        * star_progress_factor(new_s, new_p)
        / star_progress_factor(old_s, old_p)
    )
    assert scale_power_for_star_change(power, old_s, old_p, new_s, new_p) == expected


def test_scale_power_none_stays_none() -> None:
    from ks.heroes.ui.hero_power import scale_power_for_star_change

    assert scale_power_for_star_change(None, 1, 0, 2, 0) is None


def test_scale_power_includes_pellets() -> None:
    from ks.heroes.ui.hero_power import scale_power_for_star_change

    before = scale_power_for_star_change(1_000_000, 2, 0, 2, 3)
    assert before is not None
    assert before > 1_000_000


def test_hero_store_reload(tmp_path: Path) -> None:
    store = _seed(tmp_path)
    store.upsert(
        HeroRecord(
            name="Saul",
            power=500_000,
            stars=1,
            pellets=0,
            scraped_at="t",
        )
    )
    # Simulate external write
    payload = json.loads((tmp_path / "heroes.json").read_text(encoding="utf-8"))
    payload["heroes"][0]["stars"] = 4
    (tmp_path / "heroes.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    store.reload()
    helga = next(h for h in store.all_heroes() if h.name == "Helga")
    assert helga.stars == 4


def test_update_hero_stars_scales_power(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path)
    updated = update_hero_stars(store, "Helga", stars=3, pellets=0)
    assert updated.stars == 3
    assert updated.pellets == 0
    expected = round(
        1_000_000
        * star_progress_factor(3, 0)
        / star_progress_factor(2, 0)
    )
    assert updated.power == expected

    raw = json.loads((tmp_path / "heroes.json").read_text(encoding="utf-8"))
    row = next(h for h in raw["heroes"] if h["name"] == "Helga")
    assert row["stars"] == 3
    assert row["power"] == expected


def test_update_hero_stars_missing_power(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = HeroStore(tmp_path)
    store.upsert(
        HeroRecord(name="Gordon", stars=1, pellets=0, scraped_at="t")
    )
    updated = update_hero_stars(store, "Gordon", stars=2)
    assert updated.stars == 2
    assert updated.power is None


def test_update_hero_stars_rejects_range(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path)
    with pytest.raises(ValueError, match="0..5"):
        update_hero_stars(store, "Helga", stars=6)
    with pytest.raises(ValueError, match="0..5"):
        update_hero_stars(store, "Helga", pellets=6)


def test_update_hero_unknown(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path)
    with pytest.raises(KeyError):
        update_hero_stars(store, "Missing", stars=1)


def test_update_hero_level_persists_without_changing_power(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path)
    updated = update_hero_stars(store, "Helga", level=57)
    assert updated.level == 57
    assert updated.power == 1_000_000
    raw = json.loads((tmp_path / "heroes.json").read_text(encoding="utf-8"))
    row = next(h for h in raw["heroes"] if h["name"] == "Helga")
    assert row["level"] == 57


def test_hero_level_locked_against_ocr_without_overwrite(tmp_path: Path) -> None:
    from ks.heroes.ui.app import update_hero_stars

    store = _seed(tmp_path)
    update_hero_stars(store, "Helga", level=56)
    store.upsert(
        HeroRecord(
            name="Helga",
            power=1_000_000,
            level=1,
            stars=2,
            pellets=0,
            scraped_at="t2",
        )
    )
    locked = next(h for h in store.all_heroes() if h.name == "Helga")
    assert locked.level == 56


def test_fastapi_heroes_patch_and_page(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(heroes_dir=tmp_path))
    page = client.get("/heroes")
    assert page.status_code == 200
    assert b"Helga" in page.content

    listed = client.get("/api/heroes").json()["heroes"]
    assert listed[0]["name"] == "Helga"

    detail = client.get("/api/heroes/Helga")
    assert detail.status_code == 200
    assert detail.json()["hero"]["name"] == "Helga"
    assert b"hero-name-link" in page.content
    assert b"hero-detail-modal" in page.content
    assert b'data-sort="power"' in page.content
    assert b"th.sortable" in page.content or b'class="sortable"' in page.content
    assert "skills" in detail.json()["hero"]

    res = client.patch("/api/heroes/Helga", json={"stars": 3, "pellets": 2})
    assert res.status_code == 200
    body = res.json()["hero"]
    assert body["stars"] == 3
    assert body["pellets"] == 2
    assert body["power"] == round(
        1_000_000
        * star_progress_factor(3, 2)
        / star_progress_factor(2, 0)
    )


def test_fastapi_heroes_rescan_mocked(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)

    def fake_rescan(store, **_kwargs):
        store.upsert(
            HeroRecord(
                name="Helga",
                power=1_100_000,
                stars=4,
                pellets=1,
                troop_type="infantry",
                scraped_at="rescanned",
            )
        )
        return store.all_heroes()

    client = TestClient(
        create_app(heroes_dir=tmp_path, heroes_rescan_fn=fake_rescan)
    )
    res = client.post("/api/heroes/rescan")
    assert res.status_code == 200
    # One JSON document rather than an SSE stream — see the gear rescan test.
    payload = res.json()
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["trust"]["flags"] == {"Helga": "changed"}
    listed = client.get("/api/heroes").json()["heroes"]
    hero = next(h for h in listed if h["name"] == "Helga")
    assert hero["power"] == 1_100_000
    assert hero["stars"] == 4


def test_create_app_requires_inventory(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from ks.heroes.ui.app import create_app

    with pytest.raises(ValueError, match="gear_dir or heroes_dir"):
        create_app()


def test_home_redirects_to_heroes_when_no_gear(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(heroes_dir=tmp_path))
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/inventory/heroes"


def test_inventory_tabs_link_both_screens(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore
    from ks.heroes.ui.app import create_app

    heroes_dir = tmp_path / "heroes"
    gear_dir = tmp_path / "gear"
    heroes_dir.mkdir()
    gear_dir.mkdir()
    _seed(heroes_dir)
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="cell0",
            name="Test Helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=1,
            power=1000,
        )
    )
    client = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))

    # Legacy paths redirect into the Inventory/Optimiser IA; each screen marks
    # its own subtab current and links the sibling screens.
    gear_page = client.get("/gear")
    assert gear_page.status_code == 200
    assert b'href="/inventory/gear" aria-current="page"' in gear_page.content
    assert b'href="/inventory/heroes"' in gear_page.content

    heroes_page = client.get("/heroes")
    assert heroes_page.status_code == 200
    assert b'href="/inventory/heroes" aria-current="page"' in heroes_page.content
    assert b'href="/inventory/gear"' in heroes_page.content
    assert b'href="/optimiser/events"' in heroes_page.content
    assert b'href="/optimiser/events"' in gear_page.content


def test_create_manual_hero_persists_json_and_sql(tmp_path: Path) -> None:
    from ks.heroes.ui.app import create_manual_hero

    store = HeroStore(tmp_path)
    hero = create_manual_hero(store, name="Helga")
    assert hero.name == "Helga"
    assert hero.troop_type == "infantry"
    assert hero.rarity == "legendary"
    assert hero.level is None
    assert hero.stars is None
    assert hero.pellets is None
    assert hero.power is None

    raw = json.loads((tmp_path / "heroes.json").read_text(encoding="utf-8"))
    assert any(h["name"] == "Helga" for h in raw["heroes"])

    reloaded = HeroStore(tmp_path)
    found = next(h for h in reloaded.all_heroes() if h.name == "Helga")
    assert found.troop_type == "infantry"


def test_create_manual_hero_rejects_duplicate(tmp_path: Path) -> None:
    from ks.heroes.ui.app import create_manual_hero

    store = _seed(tmp_path)
    with pytest.raises(ValueError, match="already"):
        create_manual_hero(store, name="Helga")


def test_create_manual_hero_rejects_unknown(tmp_path: Path) -> None:
    from ks.heroes.ui.app import create_manual_hero

    store = HeroStore(tmp_path)
    with pytest.raises(ValueError, match="unknown"):
        create_manual_hero(store, name="NotARealHeroXYZ")


def test_create_manual_hero_case_insensitive_catalog_name(tmp_path: Path) -> None:
    from ks.heroes.ui.app import create_manual_hero

    store = HeroStore(tmp_path)
    hero = create_manual_hero(store, name="helga")
    assert hero.name == "Helga"


def test_fastapi_post_heroes_creates_hero(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    store = HeroStore(tmp_path)
    client = TestClient(create_app(heroes_dir=tmp_path))
    res = client.post("/api/heroes", json={"name": "Saul"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["hero"]["name"] == "Saul"
    assert body["hero"]["troop_type"] in {"archer", "archers"}
    assert body["hero"]["rarity"] == "legendary"

    listed = client.get("/api/heroes").json()["heroes"]
    assert any(h["name"] == "Saul" for h in listed)
    assert store  # keep lint calm if unused — reload from disk
    reloaded = HeroStore(tmp_path)
    assert any(h.name == "Saul" for h in reloaded.all_heroes())


def test_fastapi_post_heroes_rejects_duplicate(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(heroes_dir=tmp_path))
    res = client.post("/api/heroes", json={"name": "Helga"})
    assert res.status_code == 400


def test_inventory_heroes_page_has_add_control(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(heroes_dir=tmp_path))
    page = client.get("/inventory/heroes")
    assert page.status_code == 200
    assert 'id="add-hero-btn"' in page.text
    assert 'id="add-hero-dialog"' in page.text
    assert 'id="add-hero-name"' in page.text
    assert 'value="Helga"' not in page.text  # already owned
