"""Apple-light Inventory/Optimiser shell: routes, redirects, chrome, CSS."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ks.heroes.gear_models import GearRecord  # noqa: E402
from ks.heroes.gear_store import GearStore  # noqa: E402
from ks.heroes.models import HeroRecord  # noqa: E402
from ks.heroes.store import HeroStore  # noqa: E402
from ks.heroes.ui.app import create_app  # noqa: E402

SHELL_PAGES = (
    "/inventory/gear",
    "/inventory/heroes",
    "/inventory/troops",
    "/optimiser/events",
    "/optimiser/gear-xp",
    "/optimiser/hero-levels",
)


def _client(
    tmp_path: Path, *, with_gear: bool = True, with_heroes: bool = True
) -> TestClient:
    gear = heroes = None
    if with_gear:
        gear = tmp_path / "gear"
        gear.mkdir()
        (gear / "gear.json").write_text("[]", encoding="utf-8")
    if with_heroes:
        heroes = tmp_path / "heroes"
        heroes.mkdir()
        (heroes / "heroes.json").write_text("[]", encoding="utf-8")
    return TestClient(create_app(gear_dir=gear, heroes_dir=heroes))


def _seeded_client(tmp_path: Path) -> TestClient:
    gear_dir = tmp_path / "gear"
    heroes_dir = tmp_path / "heroes"
    gear_dir.mkdir()
    heroes_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="cell0",
            name="Judicator's Armet",
            troop_type="cavalry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=51,
            mastery_level=2,
            power=152_100,
        )
    )
    HeroStore(heroes_dir).upsert(
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
    return TestClient(create_app(gear_dir, heroes_dir=heroes_dir))


# --- routing -------------------------------------------------------------


def test_home_redirects_to_inventory_gear(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/inventory/gear"


def test_home_redirects_to_inventory_heroes_without_gear(tmp_path: Path) -> None:
    c = _client(tmp_path, with_gear=False)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/inventory/heroes"


def test_legacy_gear_redirects(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.get("/gear", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/inventory/gear"


@pytest.mark.parametrize(
    ("legacy", "target"),
    [
        ("/gear", "/inventory/gear"),
        ("/heroes", "/inventory/heroes"),
        ("/optimize", "/optimiser/events"),
        ("/optimize/events", "/optimiser/events"),
        ("/optimize/gear-xp", "/optimiser/gear-xp"),
    ],
)
def test_legacy_paths_redirect_to_new_ia(
    tmp_path: Path, legacy: str, target: str
) -> None:
    c = _client(tmp_path)
    r = c.get(legacy, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == target


@pytest.mark.parametrize("path", SHELL_PAGES)
def test_shell_pages_render_and_are_no_store(tmp_path: Path, path: str) -> None:
    c = _client(tmp_path)
    r = c.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


# --- chrome --------------------------------------------------------------


def test_inventory_gear_page_has_apple_shell(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.get("/inventory/gear")
    assert r.status_code == 200
    assert "Inventory" in r.text and "Optimiser" in r.text
    assert 'href="/static/app.css"' in r.text
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' in r.text


def test_stylesheet_is_served_with_apple_canvas(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.get("/static/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert "#f5f5f7" in r.text  # canvas
    assert "#0071e3" in r.text  # accent
    assert "#1d1d1f" in r.text  # text
    assert "-apple-system" in r.text


def _css_rule_body(css: str, needle: str) -> str:
    """Return the declaration block `{ ... }` of the rule containing `needle`.

    Anchors an assertion to a specific selector instead of a bare substring
    search, so the check actually breaks if that rule is edited/removed
    rather than incidentally matching some unrelated rule elsewhere.
    """
    start = css.index(needle)
    open_brace = css.index("{", start)
    close_brace = css.index("}", open_brace)
    return css[open_brace : close_brace + 1]


def test_stylesheet_is_phone_first(tmp_path: Path) -> None:
    css = _client(tmp_path).get("/static/app.css").text
    assert "env(safe-area-inset-left" in css
    assert "env(safe-area-inset-bottom" in css
    assert "max-width: 640px" in css  # narrow breakpoint

    # Scrollable table wrapper: bind to .table-wrap specifically so the
    # assertion can't be satisfied by unrelated overflow-x rules on
    # .primary-nav / .subnav.
    table_wrap = _css_rule_body(css, ".table-wrap {")
    assert "overflow-x: auto" in table_wrap

    # Sticky first column helper: bind to .data-table.sticky-first
    # specifically so the assertion can't be satisfied by unrelated
    # position: sticky rules on .app-header / .modal-header.
    sticky_first = _css_rule_body(css, ".data-table.sticky-first")
    assert "position: sticky" in sticky_first

    # Segmented subtabs are the primary phone nav control and must bind to
    # the shared 44px tap-target token, not merely contain "44px" anywhere
    # (which the --tap: 44px declaration itself would always satisfy).
    seg_rule = _css_rule_body(css, ".segmented .seg {")
    assert "var(--tap)" in seg_rule


@pytest.mark.parametrize("path", SHELL_PAGES)
def test_primary_nav_on_every_shell_page(tmp_path: Path, path: str) -> None:
    body = _client(tmp_path).get(path).text
    assert 'href="/inventory/gear"' in body
    assert 'href="/optimiser/events"' in body


def test_inventory_subnav_lists_gear_heroes_troops(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/inventory/heroes").text
    for href, label in (
        ("/inventory/gear", "Gear"),
        ("/inventory/heroes", "Heroes"),
        ("/inventory/troops", "Troops"),
    ):
        assert f'href="{href}"' in body
        assert label in body
    assert "Event lineups" not in body


def test_optimiser_subnav_lists_three_tools(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/optimiser/events").text
    for href, label in (
        ("/optimiser/events", "Event lineups"),
        ("/optimiser/gear-xp", "Gear XP"),
        ("/optimiser/hero-levels", "Hero levels"),
    ):
        assert f'href="{href}"' in body
        assert label in body
    assert "Troops" not in body


@pytest.mark.parametrize(
    ("path", "primary_href", "primary_label"),
    [
        ("/inventory/gear", "/inventory/gear", "Inventory"),
        ("/inventory/heroes", "/inventory/gear", "Inventory"),
        ("/inventory/troops", "/inventory/gear", "Inventory"),
        ("/optimiser/events", "/optimiser/events", "Optimiser"),
        ("/optimiser/gear-xp", "/optimiser/events", "Optimiser"),
        ("/optimiser/hero-levels", "/optimiser/events", "Optimiser"),
    ],
)
def test_active_primary_and_subtab_are_marked(
    tmp_path: Path, path: str, primary_href: str, primary_label: str
) -> None:
    body = _client(tmp_path).get(path).text
    assert f'<a href="{primary_href}" class="on">{primary_label}</a>' in body
    assert f'href="{path}" aria-current="page"' in body
    # Only the subtab for the page being rendered is flagged current.
    assert body.count('aria-current="page"') == 1


def test_inventory_tab_links_to_heroes_when_gear_disabled(tmp_path: Path) -> None:
    """Heroes-only app (no --gear-dir): the Inventory tab is the one
    deliberate deviation from the plan's verbatim layout HTML — its href
    must skip the gear-only default and point straight at /inventory/heroes,
    not the gear-only /inventory/gear. test_active_primary_and_subtab_are_marked
    above only ever runs with gear enabled, so it never exercises this branch.
    """
    body = _client(tmp_path, with_gear=False).get("/inventory/heroes").text
    assert '<a href="/inventory/heroes" class="on">Inventory</a>' in body


# --- capability gating ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/inventory/heroes", "/optimiser/events", "/optimiser/gear-xp", "/optimiser/hero-levels"],
)
def test_heroes_pages_404_without_heroes(tmp_path: Path, path: str) -> None:
    c = _client(tmp_path, with_heroes=False)
    assert c.get(path).status_code == 404


def test_inventory_gear_404_without_gear(tmp_path: Path) -> None:
    c = _client(tmp_path, with_gear=False)
    assert c.get("/inventory/gear").status_code == 404


def test_troops_available_for_gear_only_app(tmp_path: Path) -> None:
    c = _client(tmp_path, with_heroes=False)
    r = c.get("/inventory/troops")
    assert r.status_code == 200
    assert "Troops" in r.text


def test_disabled_sections_are_not_linked(tmp_path: Path) -> None:
    body = _client(tmp_path, with_heroes=False).get("/inventory/gear").text
    assert 'href="/inventory/heroes"' not in body
    assert 'href="/optimiser/events"' not in body
    assert 'aria-disabled="true"' in body


# --- inventory pages render real data ------------------------------------


def test_inventory_gear_renders_pieces_with_busted_icons(tmp_path: Path) -> None:
    r = _seeded_client(tmp_path).get("/inventory/gear")
    assert r.status_code == 200
    assert "Judicator" in r.text
    assert "/static/gear-pieces/" in r.text
    assert "?v=" in r.text
    assert "Rescan from OCR" in r.text
    assert 'data-sort="power"' in r.text


def test_inventory_heroes_renders_roster(tmp_path: Path) -> None:
    r = _seeded_client(tmp_path).get("/inventory/heroes")
    assert r.status_code == 200
    assert "Helga" in r.text
    assert "hero-name-link" in r.text
    assert "hero-detail-modal" in r.text
    assert "Rescan from OCR" in r.text
