"""Optimize UI page + API (sword/bear/arena/conquest)."""

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

    # Only the shell is asserted here. The lineup-board markup that used to
    # live in this test (Swordland/Bear/Arena/Conquest, Regenerate,
    # gear-detail-modal, data-regen) now has one named test each, under
    # "restoration tracking" below, against /optimiser/events rather than
    # this redirect.
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
    assert "conquest" in payload
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
    conquest = payload["conquest"]
    assert conquest["mode"] == "conquest"
    assert conquest["status"] == "Optimal"
    assert set(conquest["formation"]) == {"F1", "F2", "B1", "B2", "B3"}
    assert len(conquest["heroes"]) == 5


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
#
# All eight are restored and none is an xfail any more: Task 6 shipped
# optimiser_events.html and Task 7 shipped optimiser_gear_xp.html, so these
# are ordinary passing tests again. What each one covers on the real page is
# spelled out on the test, and the two that assert on a loose substring
# ("Bear", "grey") each pin the actual control alongside it.


def _optimiser_client(tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    heroes_dir = _seed_roster(tmp_path / "heroes")
    return TestClient(create_app(heroes_dir=heroes_dir))


def test_optimiser_events_board_shows_swordland(tmp_path: Path) -> None:
    """Restored. The three events are server-rendered segmented buttons —
    the board reads its labels back off them, so they cannot be JS-only."""
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Swordland" in page.content
    assert b'data-event="sword"' in page.content


def test_optimiser_events_board_shows_bear(tmp_path: Path) -> None:
    """Restored. `b"Bear"` is a loose needle — "Bearer", "Bearskin" or any
    hero name would satisfy it — so the Bear Trap segment itself is pinned
    alongside it rather than trusting the substring."""
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Bear" in page.content
    assert b'data-event="bear" aria-pressed="false">Bear Trap</button>' in page.content


def test_optimiser_events_board_shows_arena(tmp_path: Path) -> None:
    """Restored. Arena is the third event segment, not a separate section."""
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Arena" in page.content
    assert b'data-event="arena" aria-pressed="false">Arena</button>' in page.content


def test_optimiser_events_board_shows_conquest(tmp_path: Path) -> None:
    """Ported, not restored. Conquest came from the other branch, where it
    was a fourth `<section id="conquest-block">` on the template this merge
    deleted; the two assertions that guarded it there (`b"Conquest"` and
    `b"conquest-block"`) are re-expressed here against the new board.

    `b"Conquest"` survives verbatim but is a loose needle on its own — a
    hero name or a CSS token would satisfy it — so, as with "Bear" above,
    the control itself is pinned alongside it. `b"conquest-block"` had no
    successor to be renamed to: the section it named is gone. Its job was to
    pin that Conquest is a real region of the page rather than a heading, and
    `data-event="conquest"` is what does that job now — it is the hook
    optimiser_events.js collects with `querySelectorAll("[data-event]")` and
    reads the label back off, so a Conquest that rendered as inert text
    would fail here.
    """
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Conquest" in page.content
    assert b'data-event="conquest" aria-pressed="false">Conquest</button>' in page.content


def test_optimiser_events_board_has_regenerate(tmp_path: Path) -> None:
    """Restored. The refresh control lives in the shell's header actions."""
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"Regenerate" in page.content
    assert b'id="regen-btn"' in page.content


def test_optimiser_events_board_has_gear_detail_modal(tmp_path: Path) -> None:
    """Restored. Tapping a hero opens this; `.sheet` is what makes it a
    bottom sheet on a phone and a centred modal on a wide screen."""
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"gear-detail-modal" in page.content
    assert b'class="modal-backdrop sheet"' in page.content


def test_optimiser_events_board_has_data_regen_attr(tmp_path: Path) -> None:
    """Restored. The script collects its refresh controls by this attribute
    (it disables them all while a recompute is in flight), so the hook is
    part of the contract and not decoration."""
    page = _optimiser_client(tmp_path).get("/optimiser/events")
    assert b"data-regen=" in page.content
    assert b'data-regen="all"' in page.content


def test_optimiser_gear_xp_page_shows_heading(tmp_path: Path) -> None:
    """Restored. The screen names itself server-side: the whole answer is
    drawn later from a POST, so without this the document has no heading for
    the several seconds the spend search takes."""
    page = _optimiser_client(tmp_path).get("/optimiser/gear-xp")
    assert b"Gear XP spend" in page.content
    assert b'<h1 class="page-title">Gear XP spend</h1>' in page.content


def test_optimiser_gear_xp_page_shows_grey_rarity(tmp_path: Path) -> None:
    """Restored. `b"grey"` is a loose needle — a `.grey-row` class or a CSS
    token would satisfy it — so the grey fodder box itself is pinned
    alongside it: the label that names it, and the id/data hook the planner
    reads its count off."""
    page = _optimiser_client(tmp_path).get("/optimiser/gear-xp")
    assert b"grey" in page.content
    assert b'<label class="field-label" for="fodder-grey">' in page.content
    assert b'id="fodder-grey" data-fodder="grey" data-label="Grey"' in page.content


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


from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroStats
from ks.heroes.ui.optimize_run import run_optimize_bundle

_SHARE_KEYS = {"hero", "skills", "gear", "total"}


def _contrib_heroes() -> list[HeroRecord]:
    rows = [
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
    ]
    return [
        HeroRecord(
            name=name, troop_type=troop, rarity=rarity, stars=stars, pellets=0,
            power=power, escorts=5, roster_page=0, roster_index=i, scraped_at="t",
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for i, (name, troop, rarity, stars, power) in enumerate(rows)
    ]


def _contrib_gear() -> list[GearRecord]:
    prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}
    out: list[GearRecord] = []
    for troop in ("infantry", "cavalry", "archers"):
        for slot in ("helmet", "chest", "gloves", "boots"):
            stat = "Lethality" if slot in ("helmet", "boots") else "Health"
            out.append(
                GearRecord(
                    piece_id=f"{troop}-{slot}", name=f"{troop} {slot}",
                    troop_type=troop, slot=slot, rarity="mythic",
                    enhancement_level=40, power=60_000,
                    stats=GearStats(
                        conquest={"Hero Attack": 300, "Hero Health": 1500},
                        expedition={f"{prefix[troop]} {stat}": 32.0},
                    ),
                )
            )
    return out


def _assert_contribution(payload: dict) -> None:
    assert payload["family"] in {"conquest", "expedition"}
    assert payload["estimated"] is True
    assert set(payload["power"]) == _SHARE_KEYS
    assert payload["power"]["total"] == pytest.approx(
        payload["power"]["hero"] + payload["power"]["skills"] + payload["power"]["gear"]
    )
    for share in payload["stats"].values():
        assert set(share) == _SHARE_KEYS
        assert share["hero"] >= 0
        assert share["skills"] >= 0
        assert share["gear"] >= 0
        assert share["total"] == pytest.approx(
            share["hero"] + share["skills"] + share["gear"]
        )


def test_bundle_event_sections_carry_expedition_contributions() -> None:
    bundle = run_optimize_bundle(
        _contrib_heroes(), gear=_contrib_gear(), config_root=ROOT
    )
    for section in ("sword", "bear"):
        assert bundle[section]["stat_family"] == "expedition"
        for row in bundle[section]["modes"].values():
            assert row["stat_family"] == "expedition"
            _assert_contribution(row["formation_totals"])
            assert row["contributions"]
            for contrib in row["contributions"].values():
                _assert_contribution(contrib)


def test_bundle_combat_sections_carry_conquest_contributions() -> None:
    bundle = run_optimize_bundle(
        _contrib_heroes(), gear=_contrib_gear(), config_root=ROOT
    )
    for row in (bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]):
        if row.get("status") != "Optimal":
            continue
        assert row["stat_family"] == "conquest"
        _assert_contribution(row["formation_totals"])
        for contrib in row["contributions"].values():
            _assert_contribution(contrib)


def test_error_rows_still_declare_stat_family() -> None:
    # An empty roster makes every section infeasible; the shape must still hold.
    bundle = run_optimize_bundle([], gear=None, config_root=ROOT)
    for row in (bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]):
        assert row["stat_family"] == "conquest"
        assert row["formation_totals"] is None
        assert row["contributions"] is None
    for section in ("sword", "bear"):
        assert bundle[section]["stat_family"] == "expedition"


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
