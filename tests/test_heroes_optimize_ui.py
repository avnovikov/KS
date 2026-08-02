"""Optimize UI page + API (sword/bear modes + arena sides)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore


ROOT = Path(__file__).resolve().parents[1]


def _seed_roster(tmp_path: Path) -> Path:
    store = HeroStore(tmp_path)
    rows = [
        ("Amadeus", "infantry", "legendary", 5, 900_000),
        ("Hilde", "infantry", "legendary", 4, 700_000),
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
        ("Marlin", "archer", "legendary", 3, 350_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
    ]
    for i, (name, troop, rarity, stars, power) in enumerate(rows):
        store.upsert(
            HeroRecord(
                name=name,
                troop_type=troop,
                rarity=rarity,
                stars=stars,
                pellets=0,
                power=power,
                escorts=5,
                roster_page=0,
                roster_index=i,
                scraped_at="t",
            )
        )
    return tmp_path


def test_optimize_page_and_api(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
    client = TestClient(create_app(heroes_dir=heroes_dir))

    # The optimize hub has no successor: Optimiser lands on Event lineups.
    hub = client.get("/optimize", follow_redirects=False)
    assert hub.status_code == 302
    assert hub.headers["location"] == "/optimiser/events"

    # Lineup board markup (Swordland/Bear/Arena chips, Regenerate,
    # gear-detail-modal, data-regen) is rebuilt on the Apple shell in the
    # Event lineups task; until then only the shell is asserted here.
    page = client.get("/optimize/events")
    assert page.status_code == 200
    assert b"Event lineups" in page.content
    assert b'href="/optimiser/events" aria-current="page"' in page.content
    assert b'href="/inventory/heroes"' in page.content

    # Fodder-bag form ("Gear XP spend", rarity inputs) returns with the
    # Gear XP task.
    gear_xp = client.get("/optimize/gear-xp")
    assert gear_xp.status_code == 200
    assert b'href="/optimiser/gear-xp" aria-current="page"' in gear_xp.content

    heroes_page = client.get("/heroes")
    assert b'href="/optimiser/events"' in heroes_page.content

    payload = client.get("/api/optimize").json()
    assert "sword" in payload
    assert "bear" in payload
    assert "arena" in payload
    sword_modes = payload["sword"]["modes"]
    assert set(sword_modes) >= {"garrison", "rally_lead", "joiner", "solo"}
    for mode, row in sword_modes.items():
        assert row["recommended_mode"] == mode
        assert row["expected_personal_points"] > 0
        assert len(row["heroes"]) == 3
        assert row["heroes"][0].get("explain", {}).get("leave_one_out")
    bear_modes = payload["bear"]["modes"]
    assert len(bear_modes) >= 2
    for mode, row in bear_modes.items():
        assert row["recommended_mode"] == mode
        assert row["expected_personal_points"] > 0
    arena = payload["arena"]
    assert arena["attack"]["side"] == "attack"
    assert arena["attack"]["status"] == "Optimal"
    assert set(arena["attack"]["formation"]) == {"F1", "F2", "B1", "B2", "B3"}
    assert arena["defense"]["side"] == "defense"
    assert arena["defense"]["status"] == "Optimal"


# --- restoration tracking ---------------------------------------------------
#
# Task 1 (Apple shell) stubbed the optimiser pages, which forced the
# lineup-board and Gear-XP-form assertions below out of test_optimize_page_and_api
# above. They must come back for real once the pages that own them ship, so
# they're kept alive here as strict xfails against the *new* routes: if the
# stub still renders, xfail is a no-op; the moment real markup lands the
# assertion starts passing, strict=True turns that XPASS into a failure, and
# whoever ships the page is forced to delete the xfail mark instead of the
# coverage silently vanishing.


def _optimiser_client(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
    return TestClient(create_app(heroes_dir=heroes_dir))


@pytest.mark.xfail(
    reason="restored by Task 6: event lineups board renders a Swordland mode chip",
    strict=True,
)
def test_optimiser_events_board_shows_swordland(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Swordland" in page.content


@pytest.mark.xfail(
    reason="restored by Task 6: event lineups board renders a Bear mode chip",
    strict=True,
)
def test_optimiser_events_board_shows_bear(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Bear" in page.content


@pytest.mark.xfail(
    reason="restored by Task 6: event lineups board renders an Arena section",
    strict=True,
)
def test_optimiser_events_board_shows_arena(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Arena" in page.content


@pytest.mark.xfail(
    reason="restored by Task 6: event lineups board has a Regenerate control",
    strict=True,
)
def test_optimiser_events_board_has_regenerate(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Regenerate" in page.content


@pytest.mark.xfail(
    reason=(
        "restored by Task 6: event lineups board has a gear-detail-modal "
        "for the per-hero gear drilldown"
    ),
    strict=True,
)
def test_optimiser_events_board_has_gear_detail_modal(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"gear-detail-modal" in page.content


@pytest.mark.xfail(
    reason="restored by Task 6: Regenerate control is wired via a data-regen= attribute",
    strict=True,
)
def test_optimiser_events_board_has_data_regen_attr(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"data-regen=" in page.content


@pytest.mark.xfail(
    reason="restored by Task 7: Gear XP page renders the 'Gear XP spend' heading/form",
    strict=True,
)
def test_optimiser_gear_xp_page_shows_heading(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/gear-xp")
    assert b"Gear XP spend" in page.content


@pytest.mark.xfail(
    reason="restored by Task 7: Gear XP page renders the grey-rarity fodder input",
    strict=True,
)
def test_optimiser_gear_xp_page_shows_grey_rarity(tmp_path: Path) -> None:
    page = _optimiser_client(tmp_path).get("/optimiser/gear-xp")
    assert b"grey" in page.content


def test_optimize_gear_xp_api_smoke(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore
    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    store = GearStore(gear_dir)
    store.upsert(
        GearRecord(
            piece_id="helm1",
            name="Inf helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=5,
            power=40_000,
        )
    )
    client = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))
    # No gear → 400 when heroes-only app
    heroes_only = TestClient(create_app(heroes_dir=heroes_dir))
    denied = heroes_only.post(
        "/api/optimize/gear-xp",
        json={"event": "arena_attack", "grey": 1},
    )
    assert denied.status_code == 400

    res = client.post(
        "/api/optimize/gear-xp",
        json={
            "event": "arena_attack",
            "grey": 2,
            "green": 0,
            "blue": 0,
            "purple": 0,
            "part_100": 0,
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert "baseline_utility" in payload
    assert "best_utility" in payload
    assert "steps" in payload
    assert "leftover" in payload
    assert payload["event"] == "arena_attack"


def test_optimize_api_includes_gear_assignment_with_icons(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore
    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    store = GearStore(gear_dir)
    for i, (slot, troop) in enumerate(
        [
            ("helmet", "infantry"),
            ("chest", "infantry"),
            ("gloves", "infantry"),
            ("boots", "infantry"),
            ("helmet", "cavalry"),
            ("chest", "cavalry"),
            ("gloves", "cavalry"),
            ("boots", "cavalry"),
            ("helmet", "archers"),
            ("chest", "archers"),
            ("gloves", "archers"),
            ("boots", "archers"),
        ]
    ):
        store.upsert(
            GearRecord(
                piece_id=f"p{i}",
                name=f"{troop} {slot}",
                troop_type=troop,
                slot=slot,
                rarity="mythic",
                enhancement_level=10,
                power=50_000,
            )
        )
    client = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))
    payload = client.get("/api/optimize").json()
    garrison = payload["sword"]["modes"]["garrison"]
    assert garrison.get("gear_assignment")
    first_hero = next(iter(garrison["gear_assignment"].values()))
    assert any(p.get("icon_url") for p in first_hero)
    attack = payload["arena"]["attack"]
    assert attack.get("gear_assignment")


def test_optimize_requires_heroes(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.gear_models import GearRecord
    from ks.heroes.gear_store import GearStore
    from ks.heroes.ui.app import create_app

    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="cell0",
            name="Helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=1,
            power=1000,
        )
    )
    client = TestClient(create_app(gear_dir))
    assert client.get("/optimize").status_code == 404
    assert client.get("/api/optimize").status_code == 404
