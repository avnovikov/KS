"""Apple-light Inventory/Optimiser shell: routes, redirects, chrome, CSS."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ks.heroes.gear_models import GearRecord  # noqa: E402
from ks.heroes.gear_store import GearStore  # noqa: E402
from ks.heroes.models import HeroRecord  # noqa: E402
from ks.heroes.optimize.troops import load_troops_config  # noqa: E402
from ks.heroes.store import HeroStore  # noqa: E402
from ks.heroes.ui.app import create_app  # noqa: E402
from ks.heroes.ui.troop_store import TroopStore  # noqa: E402
from ks.heroes.ui.troops_form import troops_form_model  # noqa: E402
from ks.heroes.ui.trust import (  # noqa: E402
    flag_gear_rows,
    flag_hero_rows,
    summarize_flags,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

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


@pytest.fixture
def repo_troops() -> Path:
    return REPO_ROOT / "config" / "troops.yaml"


# Names present in config/hero_catalog.yaml — a roster of these is enough
# for recommend()/recommend_all_modes() to find a feasible sword/bear lineup,
# so build_event_utility()/run_optimize_bundle() actually run the ILP instead
# of erroring out before ever touching the troops file.
_CATALOG_HEROES = ("Helga", "Howard", "Jabel", "Chenko", "Saul", "Gordon", "Diana")


def _seed_catalog_heroes(heroes_dir: Path) -> None:
    store = HeroStore(heroes_dir)
    for name in _CATALOG_HEROES:
        store.upsert(HeroRecord(name=name, stars=3, power=300_000))


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


@pytest.mark.parametrize("path", SHELL_PAGES)
def test_every_shell_page_server_renders_one_page_title(
    tmp_path: Path, path: str
) -> None:
    """A regression this branch actually shipped: the rewrite of
    /inventory/gear and /inventory/heroes dropped the `<h1>KS Inventory</h1>`
    the deleted templates carried and started straight in on `.page-meta`.
    The gear page rendered a document with no heading of *any* level, and the
    heroes page's only one was the `<h2>` inside the detail dialog.

    Parametrised over every screen rather than asserted per page, because the
    two that lost it were exactly the two nothing checked. `.page-title`
    specifically, not a bare `<h1>`: app.css states the convention ("Screen
    heading. Server-rendered, so the document has one before any client-side
    render lands") and the class is what makes the six screens look alike.
    Exactly one, so a page cannot answer the check with a second heading
    competing for the document's title.
    """
    body = _client(tmp_path).get(path).text
    assert body.count('<h1 class="page-title">') == 1, path


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

    A renamed/removed selector is a test failure, not a helper crash: the
    `assert` reports which selector went missing instead of letting
    `str.index` raise a bare "substring not found".
    """
    assert needle in css, f"selector {needle!r} missing from the stylesheet"
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

    # "Subtabs horizontally scrollable under 640px" is an explicit global
    # constraint, and narrowing the .table-wrap assertion above left it
    # asserted by nothing. .segmented is `width: max-content` at narrow
    # widths, so the scroll has to live on the .subnav container.
    assert "overflow-x: auto" in _css_rule_body(css, ".subnav {")


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


# --- Spreadsheet+ inventory tables (Task 5) --------------------------------
#
# What these pin is the *contract between the templates and inventory.js*:
# every behaviour the script drives is declared in markup (row ids, patch
# URLs, per-field blank semantics, filter chips), so a template rename breaks
# a test here rather than silently disabling auto-save in the browser. What
# the script then *does* with those attributes is executed for real in
# tests/test_heroes_inventory_js.py.


def _spreadsheet_client(tmp_path: Path) -> TestClient:
    """Gear + heroes with enough variety to exercise filters and trust cues.

    Deliberately mixed: two troop types, one mastery-requiring rarity with
    mastery missing (incomplete), one rarity with no mastery track at all
    (complete despite a blank mastery box), one hero with no power (an
    incompleteness no amount of editing on this page can clear).
    """
    gear_dir = tmp_path / "gear"
    heroes_dir = tmp_path / "heroes"
    gear_dir.mkdir()
    heroes_dir.mkdir()
    gear = GearStore(gear_dir)
    gear.upsert(
        GearRecord(
            piece_id="cell0", name="Judicator's Armet", troop_type="cavalry",
            slot="helmet", rarity="mythic", enhancement_level=51,
            mastery_level=2, power=152_100, inventory_index=0,
        )
    )
    gear.upsert(
        GearRecord(
            piece_id="cell1", name="Scout's Cap", troop_type="infantry",
            slot="helmet", rarity="blue", enhancement_level=7,
            mastery_level=None, power=18_362, inventory_index=1,
        )
    )
    gear.upsert(
        GearRecord(
            piece_id="cell2", name="Unread Boots", troop_type="infantry",
            slot="boots", rarity="mythic", enhancement_level=None,
            mastery_level=None, inventory_index=2,
        )
    )
    heroes = HeroStore(heroes_dir)
    heroes.upsert(
        HeroRecord(
            name="Helga", power=1_000_000, troop_type="infantry",
            rarity="legendary", stars=2, pellets=0, scraped_at="t",
        )
    )
    heroes.upsert(
        HeroRecord(
            name="Gordon", power=None, troop_type="cavalry", rarity="epic",
            stars=3, pellets=1, scraped_at="t",
        )
    )
    return TestClient(create_app(gear_dir, heroes_dir=heroes_dir))


def _row_blocks(body: str) -> dict[str, str]:
    """Map each table row's `data-row-id` to its whole `<tr>…</tr>` source."""
    return {
        m.group(1): m.group(0)
        for m in re.finditer(r'data-row-id="([^"]+)".*?</tr>', body, flags=re.S)
    }


@pytest.mark.parametrize(
    ("path", "kind", "patch_base", "payload_key"),
    [
        ("/inventory/gear", "gear", "/api/gear/", "piece"),
        ("/inventory/heroes", "heroes", "/api/heroes/", "hero"),
    ],
)
def test_inventory_table_declares_its_wiring_for_the_shared_script(
    tmp_path: Path, path: str, kind: str, patch_base: str, payload_key: str
) -> None:
    """inventory.js is table-agnostic: everything that differs between the
    two pages is a data attribute, which is what lets one script serve both
    instead of the two near-identical inline copies this task deleted."""
    body = _spreadsheet_client(tmp_path).get(path).text
    assert 'id="inventory-table"' in body
    assert f'data-inventory-kind="{kind}"' in body
    assert f'data-patch-base="{patch_base}"' in body
    assert f'data-payload-key="{payload_key}"' in body
    assert 'src="/static/inventory.js"' in body


@pytest.mark.parametrize("path", ["/inventory/gear", "/inventory/heroes"])
def test_inventory_pages_ship_no_inline_script(tmp_path: Path, path: str) -> None:
    """Carried-over findings 1 and 2: both pages used to inline their own
    `showToast` (shadowing the shared one in app.js) and a verbatim copy of
    RARITY_RANK/TROOP_RANK/sortValue/sortTable. Both now come from shared
    files, so neither name may appear in the rendered HTML at all."""
    body = _spreadsheet_client(tmp_path).get(path).text
    assert "<script>" not in body
    assert "function showToast" not in body
    assert "RARITY_RANK" not in body
    assert "sortTable" not in body


@pytest.mark.parametrize("path", ["/inventory/gear", "/inventory/heroes"])
def test_per_row_save_buttons_are_gone(tmp_path: Path, path: str) -> None:
    """Auto-save replaces them; a leftover Save button would be dead UI."""
    body = _spreadsheet_client(tmp_path).get(path).text
    assert ">Save<" not in body
    assert 'class="save"' not in body
    assert 'class="save-btn"' not in body


def test_gear_rows_declare_autosave_fields_and_blank_semantics(
    tmp_path: Path,
) -> None:
    """A cleared gear box means "OCR could not read this", which the API
    spells `clear_enhancement`/`clear_mastery` — so the template, not the
    script, says how each field's blank is serialized."""
    body = _spreadsheet_client(tmp_path).get("/inventory/gear").text
    assert 'data-row-id="cell0"' in body
    assert re.search(
        r'data-field="enhancement_level"[^>]*data-blank="clear_enhancement"', body
    )
    assert re.search(
        r'data-field="mastery_level"[^>]*data-blank="clear_mastery"', body
    )
    assert 'max="200"' in body  # enhancement bound the script validates against
    assert 'max="20"' in body  # mastery


def test_hero_rows_declare_autosave_fields_and_blank_semantics(
    tmp_path: Path,
) -> None:
    """PATCH /api/heroes/{name} has no clear_* flags: a blank star box is
    sent as an explicit JSON null, which update_hero_stars maps to None."""
    body = _spreadsheet_client(tmp_path).get("/inventory/heroes").text
    assert 'data-row-id="Helga"' in body
    assert re.search(r'data-field="stars"[^>]*data-blank="null"', body)
    assert re.search(r'data-field="pellets"[^>]*data-blank="null"', body)


# --- ported from the pre-merge pages: pickers, hero level, pins, delete ----


def _lock_cells(row: str) -> dict[str, str]:
    """Map each editable field to the `<td class="lock-cell">` holding it.

    Per cell, not per row: a `data-locked` needle over a whole `<tr>` is
    satisfied by any *other* pinned cell on the same row, which is exactly
    the shape of assertion that passes for the wrong reason here.
    """
    cells: dict[str, str] = {}
    for cell in re.findall(r'<td class="lock-cell".*?</td>', row, flags=re.S):
        field = re.search(r'data-field="([a-z_]+)"', cell)
        cells[field.group(1) if field else "unrepresentable"] = cell
    return cells


def _picker(row: str, field: str) -> str:
    """The whole `<select>…</select>` for one column of one row."""
    match = re.search(
        rf'<select[^>]*data-field="{field}".*?</select>', row, flags=re.S
    )
    assert match, f"no {field} picker in row"
    return match.group(0)


def test_the_gear_pickers_offer_exactly_the_vocabulary_the_api_accepts() -> None:
    """The lists the template renders and the frozensets
    `normalize_ui_rarity`/`normalize_ui_slot` validate against are two
    spellings of one vocabulary. Let them drift and the page offers an option
    whose PATCH comes back 400 — a control that looks live and cannot be
    used. Set equality both ways, so neither a missing option nor an extra
    one survives.
    """
    from ks.heroes.ui.app import (
        _CANONICAL_RARITIES,
        _CANONICAL_SLOTS,
        UI_RARITY_CHOICES,
        UI_SLOT_CHOICES,
    )

    assert set(UI_RARITY_CHOICES) == set(_CANONICAL_RARITIES)
    assert set(UI_SLOT_CHOICES) == set(_CANONICAL_SLOTS)
    # Ordered, and not alphabetically: these are progression tiers.
    assert UI_RARITY_CHOICES == ("grey", "green", "blue", "epic", "mythic", "red")
    assert UI_SLOT_CHOICES == ("helmet", "chest", "gloves", "boots")


def test_gear_rarity_and_slot_are_editable_pickers(tmp_path: Path) -> None:
    """Restored from the page `origin/main` kept building and the rebuild
    deleted. `PATCH /api/gear/{piece_id}` has accepted both since the merge;
    only the control was missing.

    Asserted inside the `<select>` for that column, never over the row: the
    two pickers sit side by side with overlapping markup, and a needle loose
    enough to match either is a needle that pins neither.
    """
    rows = _row_blocks(_spreadsheet_client(tmp_path).get("/inventory/gear").text)
    slot = _picker(rows["cell0"], "slot")
    rarity = _picker(rows["cell0"], "rarity")

    assert re.findall(r'<option value="([a-z]*)"', slot) == [
        "",
        "helmet",
        "chest",
        "gloves",
        "boots",
    ]
    assert re.findall(r'<option value="([a-z]*)"', rarity) == [
        "",
        "grey",
        "green",
        "blue",
        "epic",
        "mythic",
        "red",
    ]
    # Exactly one selected option each, and it is the stored value.
    assert re.findall(r'<option value="([a-z]*)" selected', slot) == ["helmet"]
    assert re.findall(r'<option value="([a-z]*)" selected', rarity) == ["mythic"]

    # Same auto-save wiring as the numeric columns: a field name, the clear
    # flag its blank turns into, and the lockable mark the pin hangs off.
    for field, control, blank in (
        ("slot", slot, "clear_slot"),
        ("rarity", rarity, "clear_rarity"),
    ):
        assert 'class="cell-input' in control, field
        assert f'data-blank="{blank}"' in control
        assert f'data-sort-key="{field}"' in control
        assert "data-lockable" in control

    # A piece OCR read no slot for sits on "—", which is also the release.
    unread_dir = tmp_path / "unread"
    unread_dir.mkdir()
    GearStore(unread_dir).upsert(GearRecord(piece_id="bare", name="Bare"))
    bare = _row_blocks(
        TestClient(create_app(unread_dir)).get("/inventory/gear").text
    )["bare"]
    assert re.findall(
        r'<option value="([a-z]*)" selected', _picker(bare, "slot")
    ) == [""]
    assert re.findall(
        r'<option value="([a-z]*)" selected', _picker(bare, "rarity")
    ) == [""]


def test_a_stored_value_no_picker_can_represent_is_shown_not_offered(
    tmp_path: Path,
) -> None:
    """Every save sends the row's whole editable state, so a picker parked on
    "—" over a hand-edited `rarity: chartreuse` would silently clear it the
    first time any other box on that row moved. The cell renders the stored
    text instead — no control, nothing for `readRow` to serialize, and the
    PATCH leaves the field alone.

    OCR itself cannot produce one of these (`gear_parse`'s own maps only emit
    values `normalize_ui_*` folds), so this is about `gear.json` after a hand
    edit — which is precisely when losing data silently would be worst.
    """
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="odd",
            name="Odd",
            slot="cape",
            rarity="chartreuse",
            enhancement_level=1,
        )
    )
    row = _row_blocks(TestClient(create_app(gear_dir)).get("/inventory/gear").text)["odd"]
    cells = _lock_cells(row)

    assert "<select" not in row
    assert 'data-field="slot"' not in row
    assert 'data-field="rarity"' not in row
    assert row.count('<span class="odd-value"') == 2
    assert ">cape</span>" in row
    assert ">chartreuse</span>" in row
    # Still pinned — the store is still refusing to let OCR touch it, and the
    # page must not imply otherwise just because it cannot offer the edit.
    assert "unrepresentable" in cells
    assert 'data-locked="1"' in cells["unrepresentable"]


def test_hero_level_is_editable_beside_stars_and_pellets(tmp_path: Path) -> None:
    """`PATCH /api/heroes/{name}` has accepted `level` since the merge with
    no control anywhere. 1..80 mirrors `_HERO_LEVEL_RANGE`, and the blank is
    an explicit JSON null because that endpoint has no clear_* flag — which
    is also the only way to release the lock."""
    from ks.heroes.ui.app import _HERO_LEVEL_RANGE

    body = _spreadsheet_client(tmp_path).get("/inventory/heroes").text
    rows = _row_blocks(body)
    level = _lock_cells(rows["Helga"])["level"]

    assert 'data-blank="null"' in level
    assert f'min="{_HERO_LEVEL_RANGE.start}"' in level
    assert f'max="{_HERO_LEVEL_RANGE.stop - 1}"' in level
    assert 'data-sort-key="level"' in level
    assert 'aria-label="Level for Helga"' in level
    # Sortable, and the row carries the key the sort reads.
    assert re.search(r'class="sortable"[^>]*data-sort="level"', body)
    assert 'data-level=""' in rows["Helga"] or 'data-level="' in rows["Helga"]


def test_pinned_cells_are_marked_from_the_stored_value(tmp_path: Path) -> None:
    """§3 of the merge report: there is no lock flag on disk. For gear
    slot/rarity/enhancement/mastery and hero level, *holding a value* is what
    makes a field immune to the next rescan — so the page's predicate is
    `value is not None`, cell by cell, and nothing else.

    Checked per cell rather than per row: `cell1` is pinned on three of its
    four lockable columns and blank on the fourth, so a row-wide needle would
    report it correct whichever way the fourth went.
    """
    rows = _row_blocks(_spreadsheet_client(tmp_path).get("/inventory/gear").text)

    # cell1: blue Scout's Cap, enhancement 7, mastery unread.
    cells = _lock_cells(rows["cell1"])
    assert set(cells) == {"slot", "rarity", "enhancement_level", "mastery_level"}
    for field in ("slot", "rarity", "enhancement_level"):
        assert 'data-locked="1"' in cells[field], field
    assert "data-locked" not in cells["mastery_level"]

    # cell2: mythic boots, neither level read yet.
    cells2 = _lock_cells(rows["cell2"])
    assert "data-locked" not in cells2["enhancement_level"]
    assert "data-locked" not in cells2["mastery_level"]
    assert 'data-locked="1"' in cells2["rarity"]

    # Every lockable cell ships the pin; CSS shows it only where it belongs,
    # which keeps the marker out of the a11y tree on unpinned cells too.
    assert rows["cell1"].count('<span class="pin" role="img"') == 4


def test_a_hero_with_no_level_read_is_not_pinned(tmp_path: Path) -> None:
    """The other half of the predicate on the other table — and the case a
    single-fixture test would miss, since the seeded roster has no level at
    all until one is stored."""
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    store = HeroStore(heroes_dir)
    store.upsert(HeroRecord(name="Helga", power=1, stars=1, level=40))
    store.upsert(HeroRecord(name="Gordon", power=1, stars=1))
    rows = _row_blocks(
        TestClient(create_app(heroes_dir=heroes_dir)).get("/inventory/heroes").text
    )
    assert 'data-locked="1"' in _lock_cells(rows["Helga"])["level"]
    assert "data-locked" not in _lock_cells(rows["Gordon"])["level"]


def test_both_pages_say_what_a_pin_means_and_how_to_release_it(
    tmp_path: Path,
) -> None:
    """The pip is quiet by design — pinned is the common case, not the
    exception — so the page carries the sentence. Without it the marker is a
    dot nobody can decode, and the release (empty the field) is undiscoverable
    because it looks like destroying data rather than handing the field back.
    """
    c = _spreadsheet_client(tmp_path)
    for path in ("/inventory/gear", "/inventory/heroes"):
        hint = re.search(r'<p class="hint">(.*?)</p>', c.get(path).text, re.S)
        assert hint, path
        text = hint.group(1)
        assert "pinned" in text.lower(), path
        assert "rescan" in text.lower(), path
        assert '<span class="pin-legend">' in text, path
    # Only the gear page has pickers, so only it mentions the "—" option.
    assert "“—”" in c.get("/inventory/gear").text


def test_the_remove_button_only_arms_a_confirmation(tmp_path: Path) -> None:
    """`DELETE /api/gear/{piece_id}` survived the merge with no UI. It is
    irreversible, so the affordance is deliberately two deliberate taps: the
    row carries a full-width-word button that issues no request, and the
    dialog it arms names the piece before offering the destructive button.

    The row button must not be a submit, must not be a link to the endpoint,
    and must not be the `✕` the deleted page used — a one-character target in
    a dense row is the mis-tap this exists to prevent.
    """
    body = _spreadsheet_client(tmp_path).get("/inventory/gear").text
    rows = _row_blocks(body)
    button = re.search(r"<button[^>]*class=\"btn-remove\".*?</button>", rows["cell0"], re.S)
    assert button
    tag = button.group(0)
    assert 'type="button"' in tag
    assert 'data-remove-id="cell0"' in tag
    assert 'data-remove-name="Judicator&#39;s Armet"' in tag
    assert "aria-label=" in tag
    assert ">Remove</button>" in tag
    assert "✕" not in body
    assert "<form" not in body

    # The dialog: hidden until armed, and named for assistive tech.
    assert 'id="remove-dialog"' in body
    assert re.search(r'id="remove-dialog"[^>]*aria-hidden="true"', body)
    assert 'role="dialog"' in body and 'aria-modal="true"' in body
    assert 'id="remove-confirm"' in body
    assert 'id="remove-cancel"' in body
    assert 'id="remove-target"' in body
    # The confirm is the one destructive control in the app and says so.
    assert re.search(
        r'<button[^>]*class="btn-danger"[^>]*id="remove-confirm"[^>]*>\s*'
        r"Delete permanently",
        body,
    )
    # It cannot be reached without the dialog, and the dialog cannot be
    # reached without the row button.
    assert body.count('id="remove-confirm"') == 1


def test_the_body_the_pickers_serialize_is_one_the_api_accepts(
    tmp_path: Path,
) -> None:
    """The seam neither half of the suite can see on its own: the JS harness
    proves what `readRow` builds, the API tests prove what the endpoint
    takes, and nothing checks that they are the same document.

    Every save sends the row's *whole* editable state, so a gear PATCH now
    always carries rarity and slot — including on a row where the user only
    touched the enhancement box. Sent as the page renders them, and again
    with each picker on its clear flag, since "—" is the release control and
    a 400 there would strand a lock the user is trying to let go of.
    """
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="cell0",
            name="Judicator's Armet",
            slot="helmet",
            rarity="mythic",
            enhancement_level=51,
            mastery_level=2,
        )
    )
    client = TestClient(create_app(gear_dir))
    row = _row_blocks(client.get("/inventory/gear").text)["cell0"]

    def selected(field: str) -> str:
        return re.findall(
            r'<option value="([a-z]*)" selected', _picker(row, field)
        )[0]

    body = {
        "slot": selected("slot"),
        "rarity": selected("rarity"),
        "enhancement_level": 51,
        "mastery_level": 2,
    }
    res = client.patch("/api/gear/cell0", json=body)
    assert res.status_code == 200, res.text
    piece = res.json()["piece"]
    assert (piece["slot"], piece["rarity"]) == ("helmet", "mythic")

    cleared = client.patch(
        "/api/gear/cell0",
        json={
            "clear_slot": True,
            "clear_rarity": True,
            "enhancement_level": 51,
            "mastery_level": 2,
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["piece"]["slot"] is None
    assert cleared.json()["piece"]["rarity"] is None
    # …and a cleared field is exactly what an OCR rescan may fill again: the
    # store only keeps a value it already has. This is the whole point of the
    # release, so it is asserted against the store rather than assumed.
    store = GearStore(gear_dir)
    store.upsert(
        GearRecord(piece_id="cell0", name="Judicator's Armet", rarity="blue")
    )
    assert store.get("cell0").rarity == "blue"


def test_a_pinned_field_is_what_a_rescan_cannot_touch(tmp_path: Path) -> None:
    """The other half of the same claim, on the same route the pin renders
    from: while the field holds a value, an upsert that does not name it
    leaves it alone — so `data-locked="1"` is not decoration, it is the
    store's actual behaviour restated on screen.

    Pinned on both stores, because the pin means the same thing on both
    tables and only `GearStore` has an existing test saying so.
    """
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    store = HeroStore(heroes_dir)
    store.upsert(HeroRecord(name="Helga", power=1, stars=1, level=40))
    # A rescan reading a different level is discarded…
    store.upsert(HeroRecord(name="Helga", power=2, stars=1, level=1))
    assert next(h for h in store.all_heroes() if h.name == "Helga").level == 40
    # …until the page releases it by storing None, after which OCR wins.
    from ks.heroes.ui.app import update_hero_stars

    update_hero_stars(store, "Helga", level=None)
    store.upsert(HeroRecord(name="Helga", power=3, stars=1, level=7))
    assert next(h for h in store.all_heroes() if h.name == "Helga").level == 7


def test_the_heroes_page_has_no_delete_path(tmp_path: Path) -> None:
    """There is no `DELETE /api/heroes/{name}`, and the shared script guards
    on the dialog's absence — but the guard is only meaningful while the
    markup really is absent."""
    body = _spreadsheet_client(tmp_path).get("/inventory/heroes").text
    assert "btn-remove" not in body
    assert "remove-dialog" not in body


def test_every_id_and_hook_inventory_js_reaches_for_exists_in_the_pages(
    tmp_path: Path,
) -> None:
    """The markup/script contract, derived rather than transcribed — the same
    check the event lineups board gets. The JS harness supplies its own DOM,
    so it cannot notice a template rename; the page tests do not read the
    script. Split by page because the delete dialog is gear-only: every id is
    looked up defensively, so the heroes page is allowed to lack those four,
    and the gear page is not.
    """
    client = _spreadsheet_client(tmp_path)
    gear = client.get("/inventory/gear").text
    heroes = client.get("/inventory/heroes").text
    script = client.get("/static/inventory.js").text

    looked_up = set(re.findall(r'getElementById\("([^"]+)"\)', script))
    assert len(looked_up) >= 9, looked_up
    assert not sorted(i for i in looked_up if f'id="{i}"' not in gear)
    gear_only = {"remove-dialog", "remove-confirm", "remove-cancel", "remove-target"}
    assert gear_only < looked_up
    assert not sorted(i for i in looked_up - gear_only if f'id="{i}"' not in heroes)

    # Class hooks the script collects rather than looks up by id.
    for selector, page in (
        ("cell-input", gear),
        ("cell-input", heroes),
        ("btn-remove", gear),
    ):
        assert f'querySelectorAll("{"button." if "btn" in selector else "."}{selector}")' in script
        assert selector in page


def test_gear_page_still_ships_no_inline_script_or_style(tmp_path: Path) -> None:
    """The pickers, the pin and the confirmation dialog all landed as markup
    plus shared CSS/JS. The deleted page they came from carried 200 lines of
    inline `<style>` and a `<script>` block, which is exactly what this task
    must not reintroduce."""
    body = _spreadsheet_client(tmp_path).get("/inventory/gear").text
    assert "<style" not in body
    assert "style=" not in body
    assert "<script>" not in body
    assert re.findall(r'<script src="([^"]+)"', body) == [
        "/static/app.js",
        "/static/inventory.js",
    ]


def test_gear_icons_declare_the_size_the_stylesheet_gives_them(
    tmp_path: Path,
) -> None:
    """Carried-over finding 4: the gear icons said width/height 40 while
    `.name-cell img` sizes them at var(--tap) = 44px. CSS wins either way, so
    the mismatch only cost a first-paint reflow — but the heroes page already
    agreed at 44, and disagreeing attributes are just wrong."""
    body = _spreadsheet_client(tmp_path).get("/inventory/gear").text
    assert 'width="44" height="44"' in body
    assert 'width="40"' not in body


@pytest.mark.parametrize("path", ["/inventory/gear", "/inventory/heroes"])
def test_filter_chips_cover_all_needs_attention_and_each_troop_type(
    tmp_path: Path, path: str
) -> None:
    body = _spreadsheet_client(tmp_path).get(path).text
    assert 'data-filter="all"' in body
    assert 'data-filter="attention"' in body
    # Both fixtures carry one cavalry and one infantry row.
    for troop in ("cavalry", "infantry"):
        assert f'data-filter="troop:{troop}"' in body
    assert 'id="row-search"' in body


def test_troop_chips_are_derived_from_the_rows_actually_present(
    tmp_path: Path,
) -> None:
    """No chip for a troop type nothing on the page has — an always-empty
    filter is worse than no filter."""
    body = _spreadsheet_client(tmp_path).get("/inventory/gear").text
    assert 'data-filter="troop:archers"' not in body


def test_troop_chips_are_case_folded_before_de_duplication(
    tmp_path: Path,
) -> None:
    """The chip's data-filter and the row's data-troop are both lowercased,
    so OCR handing back "Cavalry" alongside "cavalry" would otherwise render
    two chips that filter identically — and one of them would look broken
    because both match the same rows."""
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    store = GearStore(gear_dir)
    store.upsert(GearRecord(piece_id="a", name="A", troop_type="Cavalry"))
    store.upsert(GearRecord(piece_id="b", name="B", troop_type="cavalry"))
    body = TestClient(create_app(gear_dir)).get("/inventory/gear").text
    assert body.count('data-filter="troop:cavalry"') == 1
    assert 'data-filter="troop:Cavalry"' not in body


@pytest.mark.parametrize("path", ["/inventory/gear", "/inventory/heroes"])
def test_sortable_headers_are_reachable_without_a_pointer(
    tmp_path: Path, path: str
) -> None:
    """A bare `<th>` is not focusable and has no activation behaviour, so a
    click-only sort header cannot be used from a keyboard at all. They keep
    their columnheader role — `aria-sort` is only meaningful there, so
    `role="button"` would be a downgrade — and gain `tabindex="0"`; Enter and
    Space are wired in inventory.js and executed in
    tests/test_heroes_inventory_js.py."""
    body = _spreadsheet_client(tmp_path).get(path).text
    headers = re.findall(r"<th[^>]*\bclass=\"sortable\"[^>]*>", body)
    assert headers
    for tag in headers:
        assert 'tabindex="0"' in tag, tag
        assert 'role="button"' not in tag, tag


def test_incomplete_rows_are_marked_server_side_by_the_trust_predicate(
    tmp_path: Path,
) -> None:
    """"Needs attention" must work on a plain page load, with no rescan
    payload in sessionStorage — so incompleteness is computed in Python by
    the same predicate trust.py's rescan diff uses, not re-derived in JS
    where the rarity gate would drift.
    """
    rows = _row_blocks(_spreadsheet_client(tmp_path).get("/inventory/gear").text)
    assert 'data-incomplete="1"' in rows["cell2"]  # mythic, no enhancement
    assert 'data-incomplete="1"' not in rows["cell0"]  # mythic, fully read
    # Blue gear has no mastery track at all, so its blank mastery box is
    # expected rather than a gap to chase.
    assert 'data-incomplete="1"' not in rows["cell1"]


def test_only_mastery_bearing_rarities_require_a_mastery_value(
    tmp_path: Path,
) -> None:
    """The per-input `data-required` flag is how the script re-evaluates a
    row's completeness after a save without shipping the rarity table to the
    browser. Blue gear's mastery box must not carry it."""
    blocks = _row_blocks(_spreadsheet_client(tmp_path).get("/inventory/gear").text)
    mythic = blocks["cell0"]
    blue = blocks["cell1"]
    assert re.search(r'data-field="mastery_level"[^>]*data-required', mythic, re.S)
    assert not re.search(r'data-field="mastery_level"[^>]*data-required', blue, re.S)
    assert re.search(r'data-field="enhancement_level"[^>]*data-required', blue, re.S)


def test_hero_row_with_no_power_is_incomplete_in_a_way_editing_cannot_clear(
    tmp_path: Path,
) -> None:
    """`_hero_incomplete` counts a missing power as incomplete, and nothing
    on this page can supply one (star edits rescale power, and None rescales
    to None). The row says so, or the script would helpfully un-flag it the
    first time the user touched its stars."""
    blocks = _row_blocks(_spreadsheet_client(tmp_path).get("/inventory/heroes").text)
    assert 'data-incomplete="1"' in blocks["Gordon"]
    assert 'data-incomplete-locked="1"' in blocks["Gordon"]
    assert 'data-incomplete="1"' not in blocks["Helga"]


@pytest.mark.parametrize("path", ["/inventory/gear", "/inventory/heroes"])
def test_trust_banner_and_mark_all_reviewed_are_present_but_hidden(
    tmp_path: Path, path: str
) -> None:
    """The banner is filled in from sessionStorage on the render *after* a
    rescan, so it ships hidden and the script un-hides it."""
    body = _spreadsheet_client(tmp_path).get(path).text
    assert re.search(r'id="trust-banner"[^>]*hidden', body)
    assert 'id="trust-summary"' in body
    assert 'id="mark-reviewed"' in body
    # Soft CTA, never a gate.
    assert 'href="/optimiser/events"' in body


def test_trust_cta_is_omitted_when_there_is_no_optimiser_to_link_to(
    tmp_path: Path,
) -> None:
    """A gear-only app (no --heroes) has no /optimiser/events, and the shell
    already renders that tab disabled — the banner must not smuggle a live
    link to a 404 back in."""
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(GearRecord(piece_id="cell0", name="A"))
    body = TestClient(create_app(gear_dir)).get("/inventory/gear").text
    assert 'id="trust-banner"' in body
    assert 'href="/optimiser/events"' not in body


@pytest.mark.parametrize(
    ("path", "rescan_url", "reload_url"),
    [
        ("/inventory/gear", "/api/gear/rescan", "/inventory/gear"),
        ("/inventory/heroes", "/api/heroes/rescan", "/inventory/heroes"),
    ],
)
def test_rescan_button_declares_its_endpoint_and_where_to_land(
    tmp_path: Path, path: str, rescan_url: str, reload_url: str
) -> None:
    body = _spreadsheet_client(tmp_path).get(path).text
    assert f'data-rescan-url="{rescan_url}"' in body
    assert f'data-reload-url="{reload_url}"' in body


def test_only_the_gear_rescan_asks_for_confirmation(tmp_path: Path) -> None:
    """Gear rescan wipes and replaces the whole inventory; the heroes rescan
    upserts. Only the destructive one gets a confirm dialog — which is the
    pre-existing behaviour of the two inline scripts, kept."""
    c = _spreadsheet_client(tmp_path)
    assert "data-rescan-confirm" in c.get("/inventory/gear").text
    assert "data-rescan-confirm" not in c.get("/inventory/heroes").text


def test_both_inventory_tables_keep_a_sortable_name_column(
    tmp_path: Path,
) -> None:
    c = _spreadsheet_client(tmp_path)
    body = c.get("/inventory/gear").text
    assert re.search(r'class="sortable"[^>]*data-sort="name"', body)
    assert 'data-sort="power"' in body
    heroes = c.get("/inventory/heroes").text
    assert re.search(r'class="sortable"[^>]*data-sort="name"', heroes)


def test_inventory_script_is_served_and_is_the_file_on_disk(
    tmp_path: Path,
) -> None:
    """Same wiring check troops.js gets: the <script src> resolves, the mount
    serves it as JavaScript, and the bytes on the wire are the same file the
    JS harness executes — so the two can never drift."""
    c = _spreadsheet_client(tmp_path)
    r = c.get("/static/inventory.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    on_disk = (
        REPO_ROOT / "ks" / "heroes" / "ui" / "static" / "inventory.js"
    ).read_text(encoding="utf-8")
    assert r.text == on_disk


def test_hero_detail_modal_script_is_served_to_the_heroes_page_only(
    tmp_path: Path,
) -> None:
    c = _spreadsheet_client(tmp_path)
    assert 'src="/static/hero_detail.js"' in c.get("/inventory/heroes").text
    assert 'src="/static/hero_detail.js"' not in c.get("/inventory/gear").text
    r = c.get("/static/hero_detail.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


def test_spreadsheet_styles_are_phone_first(tmp_path: Path) -> None:
    css = _client(tmp_path).get("/static/app.css").text

    # Carried-over finding 3: `min-height` on a `display: table-cell` box is
    # not what CSS 2.1 17.5.3 defines — `height` is the spec-blessed way to
    # give a cell a floor, and this header is a tap target.
    sortable = _css_rule_body(css, ".data-table th.sortable {")
    assert "height: var(--tap)" in sortable
    assert "min-height" not in sortable

    # Filter chips are tap targets, and the chip row scrolls rather than
    # widening the page at 390px.
    chip = _css_rule_body(css, ".chip {")
    assert "var(--tap)" in chip
    assert "overflow-x: auto" in _css_rule_body(css, ".chips {")

    # Trust cues use the warn token, per the design's locked palette.
    assert "var(--warn)" in _css_rule_body(css, "tr[data-trust]")

    # A rejected save is the one row state that must read as an error, and it
    # has to out-rank the trust tint (a row can be both flagged and unsaved).
    # Bound to the row rule specifically: the sticky-first companion rule
    # below it also matches a bare "tr[data-unsaved]" substring and carries
    # the same two tokens, so a looser needle would keep passing with the row
    # rule deleted outright.
    unsaved = _css_rule_body(css, ".data-table tbody tr[data-unsaved] > td")
    assert "var(--err-tint)" in unsaved
    assert "var(--err)" in unsaved
    assert css.index("tr[data-trust]") < css.index("tr[data-unsaved]")
    sticky_unsaved = _css_rule_body(
        css, ".data-table.sticky-first tr[data-unsaved] > td:first-child"
    )
    assert "var(--err)" in sticky_unsaved  # marker survives sideways scroll

    # Sortable headers are focusable, so they need the shared focus ring.
    assert ".data-table th.sortable:focus-visible" in css


def test_the_gear_pickers_are_phone_sized_and_focusable(tmp_path: Path) -> None:
    """A `<select>` picks up none of the `input[type=...]` chrome above it —
    that rule is an attribute selector on inputs — so the two pickers would
    otherwise render as bare UA dropdowns under the tap floor, in the middle
    of a table of 44px controls."""
    css = _client(tmp_path).get("/static/app.css").text
    picker = _css_rule_body(css, "select.cell-input {")
    assert "min-height: var(--tap)" in picker
    assert "var(--border)" in picker
    # The focus ring is a shared rule; `select` has to be one of its subjects
    # or the one control you can only reach by keyboard has no visible focus.
    assert "select:focus-visible" in css


def test_the_pin_is_hidden_unless_the_cell_is_pinned(tmp_path: Path) -> None:
    """The pip ships on every lockable cell and CSS decides which ones show
    it, so `data-locked` is the single source of truth for both the visual
    and the a11y tree.

    `display` specifically, not opacity or visibility: those leave the
    `role="img"` label in the accessibility tree, and a screen reader would
    announce "pinned" on every cell of every row — the exact opposite of what
    the marker is for. Both halves are bound to their own full selector: the
    hide rule and the show rule are one character apart, and a needle over
    the whole sheet would be satisfied by either.
    """
    css = _client(tmp_path).get("/static/app.css").text
    hidden = _css_rule_body(css, ".lock-cell .pin {")
    assert "display: none" in hidden
    shown = _css_rule_body(css, '.lock-cell[data-locked="1"] .pin {')
    assert "display: inline" in shown
    assert "var(--muted-soft)" in shown  # quiet: pinned is the common case
    # Source order matters — same specificity would otherwise decide it.
    assert css.index(".lock-cell .pin {") < css.index('.lock-cell[data-locked="1"] .pin {')


def test_the_destructive_controls_are_tap_sized_and_read_as_destructive(
    tmp_path: Path,
) -> None:
    """Two different weights on purpose. The row button only arms the dialog,
    so it stays a text-coloured pill like every other control on the page;
    the dialog's button is the only thing in this app that destroys data and
    is the only filled one. Both are tap targets — the row button because it
    lives in a dense table, the confirm because it must not be a sliver next
    to Cancel on a phone.
    """
    css = _client(tmp_path).get("/static/app.css").text

    row_button = _css_rule_body(css, ".btn-remove {")
    assert "min-height: var(--tap)" in row_button
    assert "var(--err-text)" in row_button  # readable red, not the fill hue
    assert "background:" not in row_button  # armed, not destructive

    confirm = _css_rule_body(css, ".btn-danger {")
    assert "min-height: var(--tap)" in confirm
    assert "background: var(--err)" in confirm

    # A confirmation is a sentence and a button; the 720px `.modal` would
    # strand it in whitespace.
    assert "width: min(26rem, 100%)" in _css_rule_body(css, ".modal.modal-confirm {")


@pytest.mark.parametrize("state", ["[data-trust]", "[data-unsaved]", ".row-saved"])
def test_row_state_tints_out_specify_row_hover_rather_than_racing_it(
    tmp_path: Path, state: str
) -> None:
    """`.data-table tbody tr:hover td` and `.data-table tbody tr<state> > td`
    are both specificity (0,2,3): the row state wins only because it happens
    to be declared later, which silently breaks the first time someone
    reorders the file — and the symptom (a flagged row losing its tint under
    the pointer, i.e. the row you are about to act on) is easy to miss.
    Listing the `:hover` variant explicitly makes it (0,3,3), so it wins
    outright.
    """
    css = _client(tmp_path).get("/static/app.css").text
    assert f".data-table tbody tr{state}:hover > td" in css


# --- Optimiser event lineups, layout B (Task 6) -----------------------------
#
# What the board *does* once it has data is executed for real in
# tests/test_heroes_optimiser_events_js.py. What is left here is the server
# half: the page renders, the API it calls still answers, the markup declares
# every hook the script reaches for, and the stylesheet gives the new controls
# phone-sized targets.


def _events_client(tmp_path: Path) -> TestClient:
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir(parents=True)
    _seed_catalog_heroes(heroes_dir)
    return TestClient(create_app(heroes_dir=heroes_dir))


def test_optimiser_events_page_and_api_smoke(tmp_path: Path) -> None:
    c = _events_client(tmp_path)
    assert c.get("/optimiser/events").status_code == 200

    api = c.get("/api/optimize")
    assert api.status_code == 200
    payload = api.json()
    # The contract the board is written against. "conquest" joined it with
    # the Conquest optimizer merge; it is a bare formation row, not a
    # {modes: ...} section or an {attack, defense} pair, which is the
    # distinction EVENT_KIND in optimiser_events.js encodes.
    assert {"sword", "bear", "arena", "conquest", "errors", "warnings"} <= set(payload)
    assert "modes" in payload["sword"]
    assert {"attack", "defense"} <= set(payload["arena"])
    conquest = payload["conquest"]
    assert "modes" not in conquest and "attack" not in conquest
    assert set(conquest["formation"]) == {"F1", "F2", "B1", "B2", "B3"}
    assert conquest["score"] is not None


def test_events_page_renders_the_four_event_segments(tmp_path: Path) -> None:
    """Server-rendered, not drawn by the script: these are the page's only
    copy of the event labels — the board reads them back off the buttons.

    Conquest is the fourth, ported from the legacy page's `#conquest-block`
    section when that template was deleted."""
    body = _events_client(tmp_path).get("/optimiser/events").text
    # The same .segmented control the subnav uses; `aria-label="Event"` is
    # what tells the two apart on a page that renders both.
    assert '<div class="segmented" role="group" aria-label="Event">' in body
    for key, label in (
        ("sword", "Swordland"),
        ("bear", "Bear Trap"),
        ("arena", "Arena"),
        ("conquest", "Conquest"),
    ):
        assert f'data-event="{key}"' in body
        assert f">{label}</button>" in body
    # Exactly these four, in this order: the board opens on the first segment
    # it finds, so a fifth appearing (or Conquest landing ahead of Swordland)
    # silently changes which screen the page lands on.
    assert re.findall(r'data-event="([a-z-]+)"', body) == [
        "sword",
        "bear",
        "arena",
        "conquest",
    ]


def test_events_page_ships_no_inline_script_or_style(tmp_path: Path) -> None:
    """Global constraint: every rule lives in app.css, and the board's logic
    lives in /static/optimiser_events.js. It was briefly inline — see the
    re-anchoring note on test_optimiser_events_page_has_esc_helper — which is
    exactly why this is pinned."""
    body = _events_client(tmp_path).get("/optimiser/events").text
    assert "<style" not in body
    assert "style=" not in body
    assert "<script>" not in body
    assert 'src="/static/optimiser_events.js"' in body


def test_every_element_the_board_script_looks_up_exists_in_the_page(
    tmp_path: Path,
) -> None:
    """The markup/script contract, derived rather than transcribed: every
    `getElementById("x")` in the served module must have a matching `id="x"`
    in the served page, and every attribute selector must match something.

    This is the one check that spans the two files. The JS harness supplies
    its own DOM, so it cannot notice a template rename; the page tests do not
    read the script. A rename on either side lands here instead of silently
    rendering an empty board in the browser.
    """
    client = _events_client(tmp_path)
    body = client.get("/optimiser/events").text
    script = client.get("/static/optimiser_events.js").text

    looked_up = set(re.findall(r'getElementById\("([^"]+)"\)', script))
    assert len(looked_up) >= 8, looked_up
    assert not sorted(i for i in looked_up if f'id="{i}"' not in body)

    selectors = set(re.findall(r'querySelectorAll\("\[([a-z-]+)\]"\)', script))
    assert selectors == {"data-event", "data-regen"}, selectors
    assert not sorted(a for a in selectors if f"{a}=" not in body)


def test_events_page_has_a_heading_before_the_solve_returns(
    tmp_path: Path,
) -> None:
    """The only other h1 on this page is injected by the board and names the
    selected *mode*, so for the several seconds the first ILP takes the
    document had no heading at all. The screen names itself server-side and
    the board's title is an h2 under it."""
    body = _events_client(tmp_path).get("/optimiser/events").text
    assert '<h1 class="page-title">Event lineups</h1>' in body
    script = _events_client(tmp_path / "second").get(
        "/static/optimiser_events.js"
    ).text
    assert '"h1"' not in script, "the board must not inject a competing h1"
    assert 'appendText("h2", "board-title"' in script


def test_the_two_regions_the_board_rewrites_are_live_regions(
    tmp_path: Path,
) -> None:
    """`#mode-note` and `#section-error` are the only nodes on this page whose
    text is replaced after load, and optimiser_events.js performs the
    un-hide-*before*-writing ceremony on both, citing app.js's toast for why.
    With no role that ceremony announced nothing: the un-hide is what makes a
    live region's later mutation observable, and neither element was one.

    polite for the skipped-modes note, assertive for a section that failed —
    the split #lineup-status (role="status") and the troops editor's
    banner-err (role="alert") already use.
    """
    body = _events_client(tmp_path).get("/optimiser/events").text
    assert '<p class="mode-note" id="mode-note" role="status" hidden>' in body
    assert '<p class="banner-err" id="section-error" role="alert" hidden>' in body


def test_event_lineups_styles_are_phone_first(tmp_path: Path) -> None:
    css = _client(tmp_path).get("/static/app.css").text

    # Mode chips are tap targets, and they reflow to two columns at 390px
    # rather than pushing the page sideways.
    assert "var(--tap)" in _css_rule_body(css, ".mode-chip {")
    assert "auto-fill" in _css_rule_body(css, ".mode-chips {")

    # So are hero slots, and the row wraps rather than widening the page.
    assert "var(--tap)" in _css_rule_body(css, ".hero-slot {")
    assert "flex-wrap: wrap" in _css_rule_body(css, ".hero-row {")

    # The event picker reuses .segmented with <button>s, so the shared pill
    # chrome every button gets has to be cleared — otherwise three pills
    # render inside a pill. Bound to the button variant specifically: the
    # `.segmented .seg` rule above it carries the tap target and would
    # satisfy a looser needle while this rule was deleted outright.
    seg = _css_rule_body(css, ".segmented button.seg {")
    assert "border: 0" in seg
    assert "background: transparent" in seg
    assert "overflow-x: auto" in _css_rule_body(css, ".seg-scroll {")

    # The portrait layers over its initials fallback, which is what a hero
    # with no artwork in /static/heroes falls back to.
    assert "position: absolute" in _css_rule_body(css, ".portrait img {")
    assert "position: relative" in _css_rule_body(css, ".portrait {")


def test_the_hero_detail_is_a_sheet_on_a_phone_and_a_modal_on_a_wide_screen(
    tmp_path: Path,
) -> None:
    """The design's own split, and the reason the backdrop carries `.sheet`:
    the rules must live inside the narrow breakpoint (a wide screen keeps the
    centred modal) and must not touch the inventory hero modal, which shares
    `.modal-backdrop` but not `.sheet`."""
    # Three apps, three directories: `_client`/`_seeded_client` each mkdir
    # their own `heroes`/`gear` under whatever root they are handed.
    for name in ("events", "shell", "inventory"):
        (tmp_path / name).mkdir()

    body = _events_client(tmp_path / "events").get("/optimiser/events").text
    assert 'class="modal-backdrop sheet"' in body

    css = _client(tmp_path / "shell").get("/static/app.css").text
    narrow_at = css.index("@media (max-width: 640px)")
    assert ".modal-backdrop.sheet" not in css[:narrow_at], (
        "the bottom sheet is leaking onto wide screens"
    )
    assert "align-items: flex-end" in _css_rule_body(css, ".modal-backdrop.sheet {")
    assert "width: 100%" in _css_rule_body(css, ".modal-backdrop.sheet .modal {")

    # Task 5's inventory modal shares the base class and must keep its shape.
    assert "align-items: center" in _css_rule_body(css, ".modal-backdrop {")
    assert 'class="modal-backdrop sheet"' not in _seeded_client(
        tmp_path / "inventory"
    ).get("/inventory/heroes").text


def test_events_page_names_the_heroes_directory_it_solved_from(
    tmp_path: Path,
) -> None:
    """Same page-meta line every other screen carries: which artifacts
    directory these numbers came out of."""
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    _seed_catalog_heroes(heroes_dir)
    body = TestClient(create_app(heroes_dir=heroes_dir)).get("/optimiser/events").text
    assert str(heroes_dir) in body


# --- trust diff helpers (Task 4) --------------------------------------------
#
# Precedence pin: when a row is both "new" (absent from `before`) and
# "incomplete" (missing progression data OCR should have read), the flag map
# reports "incomplete". A data-quality problem needs the same manual check
# whether or not the row is brand new, so folding it into "new" would hide
# the more actionable signal. "new" and "changed" can never collide on the
# same row by construction (a row is only "new" when its key is absent from
# `before`), so incomplete-over-new is the only precedence rule needed.


def test_flag_gear_rows_new_and_changed_gear() -> None:
    """The brief's own Step 1 example, with the vague `in {"new",
    "incomplete"}` assertion replaced by the pinned precedence: "b" is new
    *and* missing enhancement_level, so it reports "incomplete"."""
    before = [
        GearRecord(
            piece_id="a", name="A", enhancement_level=10, mastery_level=1, rarity="epic"
        )
    ]
    after = [
        GearRecord(
            piece_id="a", name="A", enhancement_level=12, mastery_level=1, rarity="epic"
        ),
        GearRecord(
            piece_id="b", name="B", enhancement_level=None, mastery_level=None, rarity="epic"
        ),
    ]
    flags = flag_gear_rows(before, after)
    assert flags == {"a": "changed", "b": "incomplete"}


def test_flag_gear_rows_mastery_incompleteness_is_rarity_gated() -> None:
    """Blue/green gear has no mastery track, so a missing mastery there is
    expected, not incomplete; epic/purple/mythic/red always carry one."""
    after = [
        GearRecord(piece_id="g", name="G", rarity="green", enhancement_level=1, mastery_level=None),
        GearRecord(piece_id="r", name="R", rarity="red", enhancement_level=1, mastery_level=None),
    ]
    flags = flag_gear_rows([], after)
    assert flags["g"] == "new"
    assert flags["r"] == "incomplete"


def test_flag_gear_rows_incomplete_wins_over_changed_for_a_previously_tracked_row() -> None:
    """Precedence rule 2 (see trust.py's module docstring): a row present in
    `before` whose signature differs *and* is missing data this scan reports
    "incomplete", not "changed" — this is the case that matters most for a
    trust loop: OCR read this piece fine last scan (enhancement_level=15)
    and failed to read it this scan (enhancement_level=None), which is
    exactly the regression the user is spot-checking for."""
    before = [
        GearRecord(piece_id="a", name="A", rarity="epic", enhancement_level=15, mastery_level=1)
    ]
    after = [
        GearRecord(piece_id="a", name="A", rarity="epic", enhancement_level=None, mastery_level=1)
    ]
    flags = flag_gear_rows(before, after)
    assert flags == {"a": "incomplete"}


def test_flag_gear_rows_purple_is_epics_mastery_requiring_alias() -> None:
    """normalize_rarity() lowercases/strips but does not canonicalize
    aliases, and ks/heroes/gear_parse.py's own OCR rarity map keeps "purple"
    distinct from "epic" (unlike "gold", which it already folds into
    "mythic"). power.py gives "purple" the identical curve to "epic", so
    real OCR gear can carry rarity="purple" and must still trigger the
    mastery-completeness check."""
    after = [
        GearRecord(piece_id="p", name="P", rarity="purple", enhancement_level=1, mastery_level=None),
    ]
    flags = flag_gear_rows([], after)
    assert flags["p"] == "incomplete"


def test_flag_gear_rows_reuses_normalize_rarity_for_case_and_whitespace() -> None:
    """The brief mandates reusing normalize_rarity() specifically so casing/
    whitespace in OCR'd rarity text does not let a mastery-requiring piece
    slip past the completeness check."""
    after = [
        GearRecord(piece_id="e", name="E", rarity=" Epic ", enhancement_level=1, mastery_level=None),
    ]
    flags = flag_gear_rows([], after)
    assert flags["e"] == "incomplete"


def test_flag_gear_rows_ignores_volatile_metadata_when_diffing_changed() -> None:
    """scraped_at/raw_text/detail_screenshot are rewritten by OCR on every
    rescan even when nothing meaningful moved; comparing them would mark
    every row "changed" every time and make the flag useless."""
    before = [
        GearRecord(
            piece_id="a", name="A", rarity="blue", enhancement_level=5,
            raw_text="OLD", scraped_at="2026-08-01T00:00:00Z",
            detail_screenshot="old.png",
        )
    ]
    after = [
        GearRecord(
            piece_id="a", name="A", rarity="blue", enhancement_level=5,
            raw_text="NEW", scraped_at="2026-08-02T00:00:00Z",
            detail_screenshot="new.png",
        )
    ]
    assert flag_gear_rows(before, after) == {}


def test_flag_hero_rows_new_changed_incomplete_and_unchanged() -> None:
    before = [
        HeroRecord(name="Helga", power=1_000_000, stars=2, scraped_at="t0"),
        HeroRecord(name="Steady", power=500_000, stars=1, scraped_at="t0"),
    ]
    after = [
        HeroRecord(name="Helga", power=1_100_000, stars=2, scraped_at="t1"),
        HeroRecord(name="Steady", power=500_000, stars=1, scraped_at="t1"),
        HeroRecord(name="Newbie", power=None, stars=None, scraped_at="t1"),
    ]
    flags = flag_hero_rows(before, after)
    assert flags == {"Helga": "changed", "Newbie": "incomplete"}


def test_flag_hero_rows_incomplete_when_stars_or_power_missing() -> None:
    after = [
        HeroRecord(name="NoStars", power=1000, stars=None, scraped_at="t"),
        HeroRecord(name="NoPower", power=None, stars=3, scraped_at="t"),
    ]
    flags = flag_hero_rows([], after)
    assert flags["NoStars"] == "incomplete"
    assert flags["NoPower"] == "incomplete"


def test_flag_hero_rows_flags_a_complete_hero_absent_from_before_as_new() -> None:
    """The docstring's "new means first-ever-seen" claim needs its own
    positive case: both existing "absent from before" fixtures in this
    suite are also missing stars/power, so they assert "incomplete" and
    never exercise the plain "new" branch for a hero."""
    after = [HeroRecord(name="Rookie", power=50_000, stars=1, scraped_at="t1")]
    flags = flag_hero_rows([], after)
    assert flags == {"Rookie": "new"}


def test_summarize_flags_counts_tally_the_flags_map_exactly() -> None:
    """The rescan API's new/changed/incomplete counts must never drift from
    the flags map they summarize — this tallies flags rather than
    recomputing anything, so the two can never disagree."""
    flags = {"a": "new", "b": "changed", "c": "changed", "d": "incomplete"}
    summary = summarize_flags(flags)
    assert summary == {"flags": flags, "new": 1, "changed": 2, "incomplete": 1}
    assert (
        summary["new"] + summary["changed"] + summary["incomplete"]
        == len(summary["flags"])
    )


def test_gear_rescan_api_returns_trust_flags_from_a_real_diff(tmp_path: Path) -> None:
    """Drives an actual rescan through /api/gear/rescan (OCR itself is
    stubbed via rescan_fn, same seam test_heroes_gear_ui.py uses) and
    asserts the flags the *route* produces, not just the helper in
    isolation — this is what would catch the snapshot being taken after
    the rescan instead of before it."""
    pytest.importorskip("fastapi")

    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="cell0", name="Old Armet", troop_type="cavalry", slot="helmet",
            rarity="epic", enhancement_level=10, mastery_level=1,
            inventory_page=0, inventory_index=0,
        )
    )

    def fake_rescan(store: GearStore, **_kwargs: object) -> list[GearRecord]:
        store.clear()
        store.upsert(
            GearRecord(
                piece_id="cell0", name="Old Armet", troop_type="cavalry", slot="helmet",
                rarity="epic", enhancement_level=15, mastery_level=1,
                inventory_page=0, inventory_index=0,
            )
        )
        store.upsert(
            GearRecord(
                piece_id="cell1", name="New Boots", troop_type="infantry", slot="boots",
                rarity="mythic", enhancement_level=None, mastery_level=None,
                inventory_page=0, inventory_index=1,
            )
        )
        return store.all_pieces()

    client = TestClient(create_app(gear_dir, rescan_fn=fake_rescan))
    res = client.post("/api/gear/rescan")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["count"] == 2
    trust = body["trust"]
    assert trust["flags"] == {"cell0": "changed", "cell1": "incomplete"}
    assert trust["new"] == 0
    assert trust["changed"] == 1
    assert trust["incomplete"] == 1
    assert trust["new"] + trust["changed"] + trust["incomplete"] == len(trust["flags"])
    # Existing keys are untouched by the new "trust" key.
    assert set(body.keys()) == {"ok", "count", "trust", "cache_bust", "gear"}


def test_heroes_rescan_api_returns_trust_flags_from_a_real_diff(tmp_path: Path) -> None:
    """Same real-route coverage for the upserting heroes rescan: "new" must
    mean first-ever-seen, and an untouched hero must not flag "changed"
    just because its scraped_at moved."""
    pytest.importorskip("fastapi")

    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    store = HeroStore(heroes_dir)
    store.upsert(HeroRecord(name="Helga", power=1_000_000, stars=2, scraped_at="t0"))
    store.upsert(HeroRecord(name="Steady", power=200_000, stars=1, scraped_at="t0"))

    def fake_rescan(store: HeroStore, **_kwargs: object) -> list[HeroRecord]:
        store.upsert(HeroRecord(name="Helga", power=1_200_000, stars=2, scraped_at="t1"))
        store.upsert(HeroRecord(name="Steady", power=200_000, stars=1, scraped_at="t1"))
        store.upsert(HeroRecord(name="Newbie", power=None, stars=None, scraped_at="t1"))
        return store.all_heroes()

    client = TestClient(create_app(heroes_dir=heroes_dir, heroes_rescan_fn=fake_rescan))
    res = client.post("/api/heroes/rescan")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["count"] == 3
    trust = body["trust"]
    assert trust["flags"] == {"Helga": "changed", "Newbie": "incomplete"}
    assert trust["new"] == 0
    assert trust["changed"] == 1
    assert trust["incomplete"] == 1
    assert trust["new"] + trust["changed"] + trust["incomplete"] == len(trust["flags"])
    assert set(body.keys()) == {"ok", "count", "trust", "cache_bust", "heroes"}


# --- TroopStore ------------------------------------------------------------


def test_troop_store_seeds_and_roundtrips(tmp_path: Path, repo_troops: Path) -> None:
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    raw = store.load_raw()
    assert "march_capacity" in raw
    raw["march_capacity"] = 90000
    saved = store.save_raw(raw)
    assert saved["march_capacity"] == 90000
    cfg = load_troops_config(dest)
    assert cfg.march_capacity == 90000


def test_troop_store_ensure_exists_does_not_clobber_edits(
    tmp_path: Path, repo_troops: Path
) -> None:
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    edited = store.load_raw()
    edited["march_capacity"] = 12345
    store.save_raw(edited)

    store.ensure_exists()  # file already exists — must be a no-op, not re-seed

    assert store.load_raw()["march_capacity"] == 12345


def test_troop_store_save_raw_still_validates_merged_result(
    tmp_path: Path, repo_troops: Path
) -> None:
    """save_raw() now merges the PUT body into the existing document (see
    Important 3), so omitting a key from the body is not itself an error —
    it inherits the existing value. But the *merged* result must still be
    validated: if the on-disk document is itself incomplete (e.g. an old or
    hand-corrupted file missing a type key entirely), save_raw() must still
    surface that as ValueError rather than silently persisting it forever.
    """
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    incomplete = store.load_raw()
    del incomplete["archers"]
    dest.write_text(yaml.safe_dump(incomplete, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="archers"):
        store.save_raw({"march_capacity": 100})


def test_troop_store_save_raw_preserves_truegold_which_validation_ignores(
    tmp_path: Path, repo_troops: Path
) -> None:
    """truegold is not part of TroopsConfig, so troops_config_from_dict never
    looks at it — but the store must still round-trip it faithfully since the
    optimisers read it back out of the raw YAML separately.
    """
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    raw = store.load_raw()
    raw["truegold"] = 4
    store.save_raw(raw)
    assert store.load_raw()["truegold"] == 4


def test_troop_store_save_raw_merge_preserves_omitted_truegold(
    tmp_path: Path, repo_troops: Path
) -> None:
    """Important 3: a PUT body that omits truegold must not delete it — a
    partial save_raw() call is a top-level merge, not an overwrite. Losing
    truegold here would silently reintroduce the "truegold comes from
    somewhere other than the UI" failure this task existed to eliminate.
    """
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    raw = store.load_raw()
    raw["truegold"] = 4
    store.save_raw(raw)

    partial = store.load_raw()
    del partial["truegold"]
    saved = store.save_raw(partial)

    assert saved["truegold"] == 4
    assert store.load_raw()["truegold"] == 4


def test_troop_store_save_raw_present_type_block_replaces_whole_block(
    tmp_path: Path, repo_troops: Path
) -> None:
    """A type block that IS present in the body replaces the whole block —
    tiers are not deep-merged — so a client clearing a tier to 0 can send
    the full replacement block and have old tiers actually disappear.
    """
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    before = store.load_raw()
    assert before["infantry"][3] == 1015  # seeded tier present

    saved = store.save_raw({**before, "infantry": {6: 10}})

    assert saved["infantry"] == {6: 10}
    assert store.load_raw()["infantry"] == {6: 10}


def test_troop_store_save_raw_wraps_typeerror_from_null_march_capacity(
    tmp_path: Path, repo_troops: Path
) -> None:
    """Important 1: troops_config_from_dict raises TypeError (int(None)) for
    a null march_capacity, not ValueError. save_raw() must catch that and
    re-raise as ValueError so non-HTTP callers (and the route's 422 mapping)
    see a consistent exception type for any invalid shape.
    """
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    raw = store.load_raw()
    raw["march_capacity"] = None
    with pytest.raises(ValueError):
        store.save_raw(raw)


def test_troop_store_ensure_exists_falls_back_to_empty_when_no_seed_configured(
    tmp_path: Path,
) -> None:
    """Minor 10: the no-seed-configured case (seed_from=None) must keep
    working exactly as before — only a *configured* seed_from pointing at a
    missing file should fail loudly.
    """
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest)
    store.ensure_exists()
    assert store.load_raw()["march_capacity"] == 0


def test_troop_store_ensure_exists_raises_when_seed_from_missing(
    tmp_path: Path,
) -> None:
    """Minor 10: a configured seed_from that does not exist (e.g. a wrong
    repo-root guess when installed as a package) must fail loudly naming the
    path it looked for, instead of silently seeding an all-zero army.
    """
    dest = tmp_path / "troops.yaml"
    missing_seed = tmp_path / "does-not-exist.yaml"
    store = TroopStore(dest, seed_from=missing_seed)
    with pytest.raises(FileNotFoundError, match=re.escape(str(missing_seed))):
        store.ensure_exists()
    assert not dest.exists()


# --- /api/troops -------------------------------------------------------


def test_put_troops_rejects_negative(tmp_path: Path) -> None:
    c = _client(tmp_path, with_gear=False)
    body = {
        "march_capacity": 80280,
        "truegold": 0,
        "infantry": {"1": -5},
        "cavalry": 0,
        "archers": 0,
    }
    r = c.put("/api/troops", json=body)
    assert r.status_code == 422
    assert "infantry" in r.json()["detail"]


def test_get_troops_returns_seeded_raw_and_totals(tmp_path: Path) -> None:
    c = _client(tmp_path, with_gear=False)
    r = c.get("/api/troops")
    assert r.status_code == 200
    body = r.json()
    assert body["troops"]["march_capacity"] == 80280
    assert body["troops"]["truegold"] == 0
    assert body["totals"] == {
        "march_capacity": 80280,
        "infantry": 33858,
        "cavalry": 27924,
        "archers": 29386,
    }


def test_put_troops_persists_and_get_reflects_update(tmp_path: Path) -> None:
    c = _client(tmp_path, with_gear=False)
    body = {
        "march_capacity": 90000,
        "truegold": 3,
        "infantry": {"1": 10},
        "cavalry": 0,
        "archers": 0,
    }
    r = c.put("/api/troops", json=body)
    assert r.status_code == 200
    saved = r.json()
    assert saved["troops"]["march_capacity"] == 90000
    assert saved["troops"]["truegold"] == 3
    assert saved["totals"]["infantry"] == 10

    again = c.get("/api/troops").json()
    assert again["troops"]["truegold"] == 3
    assert again["totals"]["march_capacity"] == 90000


def test_put_troops_null_march_capacity_returns_422(tmp_path: Path) -> None:
    """Important 1: troops_config_from_dict raises TypeError (int(None)) for
    a null march_capacity — the exact shape a blank numeric input in Task
    3's form serializes to. This must map to 422, not a bare 500.
    """
    c = _client(tmp_path, with_gear=False)
    body = c.get("/api/troops").json()["troops"]
    body["march_capacity"] = None
    r = c.put("/api/troops", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]


def test_put_troops_null_tier_count_returns_422(tmp_path: Path) -> None:
    """Important 1: a null tier count also raises TypeError under the hood
    (int(None) inside _parse_type_block), must also map to 422."""
    c = _client(tmp_path, with_gear=False)
    body = c.get("/api/troops").json()["troops"]
    body["infantry"] = {"1": None}
    r = c.put("/api/troops", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]


def test_put_troops_object_valued_march_capacity_returns_422(tmp_path: Path) -> None:
    """Important 1: an object-valued march_capacity (int(dict) -> TypeError)
    must also map to 422, not 500."""
    c = _client(tmp_path, with_gear=False)
    body = c.get("/api/troops").json()["troops"]
    body["march_capacity"] = {"oops": "not a number"}
    r = c.put("/api/troops", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]


def test_get_troops_returns_422_on_corrupt_yaml(tmp_path: Path) -> None:
    """Important 2: corrupt on-disk YAML (e.g. from a hand edit, or an
    interrupted non-atomic write_text) must surface as 422 with the parse
    error, not a blank 500 — GET should be at least as diagnosable as PUT.
    """
    c = _client(tmp_path, with_gear=False)
    assert c.get("/api/troops").status_code == 200  # seeds the file first
    (tmp_path / "heroes" / "troops.yaml").write_text(
        "march_capacity: [unterminated\n", encoding="utf-8"
    )
    r = c.get("/api/troops")
    assert r.status_code == 422
    assert r.json()["detail"]


def test_put_troops_repairs_corrupt_on_disk_file(tmp_path: Path) -> None:
    """Fix wave 2 regression: save_raw() became read-modify-write for the
    Important 3 merge, so a PUT with unreadable existing content on disk
    used to 500 (yaml.YAMLError propagating from the load-before-merge, not
    caught by the route's `except ValueError`). A blind-overwrite PUT could
    always repair a corrupt troops.yaml before that change; merging must not
    remove that self-healing path. save_raw() now treats an existing
    document that fails to *parse* as "nothing to merge from", so a
    complete, valid PUT body still repairs the file.
    """
    c = _client(tmp_path, with_gear=False)
    assert c.get("/api/troops").status_code == 200  # seeds the file first
    troops_path = tmp_path / "heroes" / "troops.yaml"
    troops_path.write_text("march_capacity: [unterminated\n", encoding="utf-8")

    good = {
        "march_capacity": 12345,
        "truegold": 2,
        "infantry": {"1": 10},
        "cavalry": {"1": 5},
        "archers": {"1": 3},
    }
    r = c.put("/api/troops", json=good)
    assert r.status_code == 200, r.text
    assert r.json()["troops"]["march_capacity"] == 12345

    again = c.get("/api/troops")
    assert again.status_code == 200
    assert again.json()["troops"]["march_capacity"] == 12345
    # File itself is valid YAML again, not just the API's view of it.
    assert yaml.safe_load(troops_path.read_text(encoding="utf-8"))["march_capacity"] == 12345


def test_get_troops_returns_422_on_invalid_content(tmp_path: Path) -> None:
    """Important 2: valid YAML that fails troops validation (missing a
    required key) must also surface as 422 with the validator's message —
    the same content PUT already rejects with a readable 422, not a blank
    500 on the read side.
    """
    c = _client(tmp_path, with_gear=False)
    assert c.get("/api/troops").status_code == 200  # seeds the file first
    (tmp_path / "heroes" / "troops.yaml").write_text(
        yaml.safe_dump({"march_capacity": 100, "infantry": 0, "cavalry": 0}),
        encoding="utf-8",
    )
    r = c.get("/api/troops")
    assert r.status_code == 422
    assert "archers" in r.json()["detail"]


def test_put_troops_without_truegold_preserves_existing_value(tmp_path: Path) -> None:
    """Important 3: PUT is a top-level merge — a body that omits truegold
    must not delete it (confirmed bug: truegold=0 went GONE after a partial
    PUT before this fix)."""
    c = _client(tmp_path, with_gear=False)
    troops = c.get("/api/troops").json()["troops"]
    troops["truegold"] = 4
    assert c.put("/api/troops", json=troops).status_code == 200

    partial = dict(troops)
    del partial["truegold"]
    r = c.put("/api/troops", json=partial)
    assert r.status_code == 200
    assert r.json()["troops"]["truegold"] == 4
    assert c.get("/api/troops").json()["troops"]["truegold"] == 4


def test_put_troops_present_tier_block_replaces_whole_block(tmp_path: Path) -> None:
    """Important 3: a type block present in the body replaces the whole
    block rather than deep-merging tier by tier, so a client can clear a
    tier by omitting it from the replacement block."""
    c = _client(tmp_path, with_gear=False)
    troops = c.get("/api/troops").json()["troops"]
    assert troops["infantry"]["3"] == 1015  # seeded tier present

    body = {**troops, "infantry": {"6": 10}}
    r = c.put("/api/troops", json=body)
    assert r.status_code == 200
    assert r.json()["troops"]["infantry"] == {"6": 10}
    assert c.get("/api/troops").json()["troops"]["infantry"] == {"6": 10}


def test_troops_file_lives_in_heroes_dir_when_both_configured(tmp_path: Path) -> None:
    c = _client(tmp_path)  # both gear and heroes configured
    assert c.get("/api/troops").status_code == 200
    assert (tmp_path / "heroes" / "troops.yaml").is_file()
    assert not (tmp_path / "gear" / "troops.yaml").exists()


def test_troops_file_lives_in_gear_dir_when_heroes_not_configured(
    tmp_path: Path,
) -> None:
    c = _client(tmp_path, with_heroes=False)
    assert c.get("/api/troops").status_code == 200
    assert (tmp_path / "gear" / "troops.yaml").is_file()


# --- troops editor page ----------------------------------------------------


def test_troops_page_renders_form(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.get("/inventory/troops")
    assert r.status_code == 200
    assert "march_capacity" in r.text or "March" in r.text


def test_troops_page_renders_seeded_values(tmp_path: Path) -> None:
    """The form is server-rendered from the store, so the page is useful
    before any JS runs and never flashes empty inputs."""
    body = _client(tmp_path).get("/inventory/troops").text
    assert 'data-field="march_capacity"' in body
    assert 'value="80280"' in body  # seeded march_capacity
    assert 'data-field="truegold"' in body
    # Seeded infantry T3 = 1015 (config/troops.yaml).
    assert re.search(
        r'data-type="infantry"[^>]*data-tier="3"[^>]*value="1015"', body
    )


def test_troops_page_shows_per_type_totals(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/inventory/troops").text
    for key, total in (
        ("infantry", "33,858"),
        ("cavalry", "27,924"),
        ("archers", "29,386"),
    ):
        assert f'data-total-for="{key}"' in body
        assert total in body


def test_troops_page_stacks_one_card_per_type_not_a_matrix(tmp_path: Path) -> None:
    """Phone-first: three stacked per-type cards, never a squeezed 3x11
    table."""
    body = _client(tmp_path).get("/inventory/troops").text
    for key in ("infantry", "cavalry", "archers"):
        assert f'data-troop-type="{key}"' in body
    assert body.count("data-tier=") == 33  # 3 types x tiers 1..11
    assert "<table" not in body


def test_troops_page_inputs_are_non_negative_integer_fields(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/inventory/troops").text
    tier_inputs = re.findall(r"<input[^>]*data-tier=[^>]*>", body)
    assert len(tier_inputs) == 33
    for tag in tier_inputs:
        assert 'type="number"' in tag
        assert 'min="0"' in tag
        assert 'step="1"' in tag
        assert 'inputmode="numeric"' in tag


def test_troops_page_survives_unreadable_troops_file(tmp_path: Path) -> None:
    """A hand-mangled or half-written troops.yaml must not 500 the editor —
    it renders with a banner and zeroed fields the user can repair (PUT is
    self-healing over corrupt YAML)."""
    c = _client(tmp_path)
    assert c.get("/inventory/troops").status_code == 200  # seeds the file
    (tmp_path / "heroes" / "troops.yaml").write_text(
        "march_capacity: [unterminated\n", encoding="utf-8"
    )
    r = c.get("/inventory/troops")
    assert r.status_code == 200
    assert "troops-load-error" in r.text
    assert 'data-field="march_capacity"' in r.text


def test_troops_page_flags_invalid_content_but_keeps_readable_fields(
    tmp_path: Path,
) -> None:
    c = _client(tmp_path)
    assert c.get("/inventory/troops").status_code == 200  # seeds the file
    (tmp_path / "heroes" / "troops.yaml").write_text(
        yaml.safe_dump({"march_capacity": 4242, "infantry": 0, "cavalry": 0}),
        encoding="utf-8",
    )
    r = c.get("/inventory/troops")
    assert r.status_code == 200
    assert "troops-load-error" in r.text
    assert "archers" in r.text
    assert 'value="4242"' in r.text  # readable field survives the failure


def test_troops_page_fields_round_trip_through_the_api(tmp_path: Path) -> None:
    """The rendered field names must themselves be a valid PUT body.

    troops.js saves the whole document scraped out of these data attributes,
    so this walks the same path in Python: scrape the form, change a tier,
    PUT it, and check the page re-renders the saved value. Catches drift
    between the template's attribute names and the API contract, which no
    amount of HTML-substring smoke testing would.
    """
    c = _client(tmp_path)
    body = c.get("/inventory/troops").text
    doc: dict[str, Any] = {}
    for field, value in re.findall(r'data-field="(\w+)"[^>]*?value="(\d+)"', body):
        doc[field] = int(value)
    for troop, tier, value in re.findall(
        r'data-type="(\w+)"\s+data-tier="(\d+)"[^>]*?value="(\d+)"', body
    ):
        doc.setdefault(troop, {})[tier] = int(value)
    assert sorted(doc) == ["archers", "cavalry", "infantry", "march_capacity", "truegold"]
    assert doc["march_capacity"] == 80280
    assert len(doc["infantry"]) == 11

    doc["infantry"]["6"] = 42  # seeded 30084
    r = c.put("/api/troops", json=doc)
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["infantry"] == 33858 - 30084 + 42

    reloaded = c.get("/inventory/troops").text
    assert re.search(r'data-type="infantry"\s+data-tier="6"[^>]*?value="42"', reloaded)
    assert 'value="80280"' in reloaded  # untouched fields survived the save


def test_troops_editor_script_is_served(tmp_path: Path) -> None:
    """The page asks for troops.js and the mount hands back that exact file.

    Deliberately not a substring grep for "PUT" or "/api/troops": what the
    script *does* is executed for real in tests/test_heroes_troops_editor_js.py,
    and the API contract is covered by the round trip above. What is left for
    this test is the wiring — that the page's <script src> resolves, that the
    static mount serves it as JavaScript, and that the bytes on the wire are
    the same file the JS harness runs, so neither can drift from the other.
    """
    c = _client(tmp_path)
    page = c.get("/inventory/troops").text
    assert 'src="/static/troops.js"' in page
    # The save URL is the page's to declare; the script only falls back to it.
    assert 'data-save-url="/api/troops"' in page

    r = c.get("/static/troops.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    on_disk = (
        REPO_ROOT / "ks" / "heroes" / "ui" / "static" / "troops.js"
    ).read_text(encoding="utf-8")
    assert r.text == on_disk

    # The script reports a load-time clamp into a persistent banner rather
    # than the shared #toast, which the next message overwrites. The JS
    # harness supplies that element from its fake DOM, so it cannot notice if
    # the template stops shipping it — hence this end of the contract.
    assert 'id="troops-repair-notice"' in page
    assert 'getElementById("troops-repair-notice")' in on_disk


def test_shared_app_js_is_loaded_by_every_shell_page(tmp_path: Path) -> None:
    """Task 5 extracts the duplicated inline showToast; this task lands the
    shared file and wires it into the layout so no third copy is added."""
    c = _client(tmp_path)
    for path in SHELL_PAGES:
        assert 'src="/static/app.js"' in c.get(path).text
    r = c.get("/static/app.js")
    assert r.status_code == 200
    assert "window.showToast" in r.text

    # The live region must have `hidden` toggled as a property alongside the
    # class, and the message written only once it is visible.
    #
    # Pinned to the two exact statements. `text.index(sub, start) > start` can
    # never be false, so the obvious spelling of this check is a tautology: it
    # keeps passing even with the assignments swapped, because the `el.
    # textContent = ""` inside the hide timeout always follows anyway. The
    # ordering is *executed* in tests/test_heroes_troops_editor_js.py, which
    # records the writes app.js actually performs; this is the cheap
    # source-level twin of that.
    unhide = r.text.index("el.hidden = false;")
    written = r.text.index("el.textContent = String(message);")
    assert written > unhide, "the message is written before the region is shown"


def test_troops_form_styles_are_phone_friendly(tmp_path: Path) -> None:
    css = _client(tmp_path).get("/static/app.css").text
    summary = _css_rule_body(css, ".troop-summary {")
    assert "var(--tap)" in summary
    grid = _css_rule_body(css, ".tier-grid {")
    assert "auto-fill" in grid  # reflows to 1-2 columns at 390px


# --- troops form model -----------------------------------------------------


def test_troops_form_model_covers_tiers_1_to_11_for_every_type() -> None:
    form = troops_form_model({})
    assert form.march_capacity == 0
    assert form.truegold == 0
    assert [t.key for t in form.types] == ["infantry", "cavalry", "archers"]
    for troop_type in form.types:
        assert [row.tier for row in troop_type.tiers] == list(range(1, 12))
        assert troop_type.total == 0


def test_troops_form_model_reads_int_and_string_tier_keys() -> None:
    """YAML seeds int keys; every PUT round-trip writes JSON string keys."""
    form = troops_form_model({"infantry": {3: 5, "6": 7}})
    infantry = form.types[0]
    counts = {row.tier: row.count for row in infantry.tiers}
    assert counts[3] == 5
    assert counts[6] == 7
    assert infantry.total == 12


def test_troops_form_model_keeps_tiers_beyond_eleven() -> None:
    """Saving replaces a whole type block, so a tier the form did not render
    would be silently deleted."""
    form = troops_form_model({"cavalry": {13: 4}})
    cavalry = form.types[1]
    assert [row.tier for row in cavalry.tiers] == list(range(1, 12)) + [13]
    assert cavalry.total == 4


def test_troops_form_model_treats_flat_int_block_as_tier_one() -> None:
    """Matches _parse_type_block: a bare int means that many tier-1 troops."""
    form = troops_form_model({"archers": 500})
    archers = form.types[2]
    assert archers.tiers[0].count == 500
    assert archers.total == 500


def test_troops_form_model_tolerates_junk_without_raising() -> None:
    form = troops_form_model(
        {
            "march_capacity": "nope",
            "truegold": None,
            "infantry": {"x": 1, "2": "3"},
            "cavalry": ["not", "a", "block"],
        }
    )
    assert form.march_capacity == 0
    assert form.truegold == 0
    counts = {row.tier: row.count for row in form.types[0].tiers}
    assert counts[2] == 3  # string count coerced
    assert form.types[1].total == 0  # unusable block renders as zeros


# --- optimisers read the edited troops copy, not config/troops.yaml -------


def test_optimize_api_uses_edited_troops_not_repo_file(tmp_path: Path) -> None:
    """Regression for the two-read truegold bug: build_event_utility/
    _event_bundle read truegold via a *second*, separate yaml.safe_load of
    the troops file. If that second read stayed hardcoded to the repo's
    config/troops.yaml, editing truegold through the API would silently have
    no effect on the returned score even though counts were wired correctly.
    """
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    _seed_catalog_heroes(heroes_dir)
    c = TestClient(create_app(heroes_dir=heroes_dir))

    baseline = c.get("/api/optimize").json()
    baseline_score = baseline["sword"]["modes"]["garrison"]["expected_personal_points"]
    assert baseline_score > 0

    troops = c.get("/api/troops").json()["troops"]
    assert troops["truegold"] == 0  # seeded from config/troops.yaml
    troops["truegold"] = 5
    assert c.put("/api/troops", json=troops).status_code == 200

    updated = c.get("/api/optimize").json()
    updated_score = updated["sword"]["modes"]["garrison"]["expected_personal_points"]

    assert updated_score != baseline_score


def test_gear_xp_api_uses_edited_troops_not_repo_file(tmp_path: Path) -> None:
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    _seed_catalog_heroes(heroes_dir)
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="p0",
            name="Test Helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=0,
            power=1000,
        )
    )
    c = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))

    fodder = {
        "event": "swordland",
        "grey": 0,
        "green": 0,
        "blue": 0,
        "purple": 0,
        "part_100": 0,
    }
    baseline = c.post("/api/optimize/gear-xp", json=fodder)
    assert baseline.status_code == 200, baseline.text
    baseline_utility = baseline.json()["baseline_utility"]

    troops = c.get("/api/troops").json()["troops"]
    troops["truegold"] = 5
    assert c.put("/api/troops", json=troops).status_code == 200

    updated = c.post("/api/optimize/gear-xp", json=fodder)
    assert updated.status_code == 200, updated.text
    updated_utility = updated.json()["baseline_utility"]

    assert updated_utility != baseline_utility


def test_gear_xp_api_uses_edited_march_capacity_and_tier_counts_not_repo_file(
    tmp_path: Path,
) -> None:
    """Minor 4: the two tests above only ever mutate truegold, so they stay
    green even if `load_troops_config(resolved_troops_path)` in
    spend_xp.build_event_utility were reverted to
    `load_troops_config(root / "config" / "troops.yaml")` — that revert
    leaves the separate truegold read (which already uses resolved_troops_
    path) wired correctly, so only march_capacity/tier counts would silently
    keep coming from the repo file. This test edits capacity and a tier
    count instead, and checks against an independently computed expected
    value (not a bare !=): the same recommend_all_modes() call
    build_event_utility makes internally, but fed troops loaded explicitly
    from the edited file — so a revert that reads the wrong file produces a
    detectably wrong number, not just "a different" one.
    """
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    _seed_catalog_heroes(heroes_dir)
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="p0",
            name="Test Helm",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=0,
            power=1000,
        )
    )
    c = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))

    fodder = {
        "event": "swordland",
        "grey": 0,
        "green": 0,
        "blue": 0,
        "purple": 0,
        "part_100": 0,
    }

    troops = c.get("/api/troops").json()["troops"]
    troops["march_capacity"] = 40000  # far from the seeded 80280
    troops["infantry"] = {"6": 5000}  # replaces the whole block; deterministic
    put = c.put("/api/troops", json=troops)
    assert put.status_code == 200, put.text
    saved = put.json()["troops"]

    result = c.post("/api/optimize/gear-xp", json=fodder)
    assert result.status_code == 200, result.text
    actual_utility = result.json()["baseline_utility"]

    # Ground truth: reproduce build_event_utility's internal no-mode branch
    # for "swordland" by hand, loading troops explicitly from the edited
    # file — independent of whichever path the code under test actually
    # reads for the TroopsConfig half of the wiring.
    #
    # This intentionally mirrors two specific choices made in
    # ks/heroes/optimize/spend_xp.py's build_event_utility(): the
    # gear_profile="early_game_growth" literal set for the sword/swordland
    # branch, and the `max(results.values(), key=lambda r:
    # r.expected_personal_points)` mode-selection rule in its no-`mode`
    # branch. If either of those legitimately changes, update the
    # corresponding line below to match, or this test starts asserting
    # against a stale ground truth.
    from ks.heroes.optimize.catalog import load_catalog
    from ks.heroes.optimize.events import load_event_profile
    from ks.heroes.optimize.recommend import recommend_all_modes
    from ks.heroes.optimize.scenarios import load_scenarios
    from ks.heroes.optimize.troop_stats import load_troop_stats

    troops_path = heroes_dir / "troops.yaml"
    catalog = load_catalog(None, REPO_ROOT / "config" / "hero_catalog.yaml")
    scenarios = load_scenarios(REPO_ROOT / "config" / "point_scenarios.yaml")
    event_profile = load_event_profile(
        REPO_ROOT / "config" / "events" / "swordland.yaml"
    )
    troop_stats = load_troop_stats(REPO_ROOT / "config" / "troop_stats.yaml")
    troops_cfg = load_troops_config(troops_path)
    heroes = HeroStore(heroes_dir).all_heroes()
    gear_pieces = GearStore(gear_dir).all_pieces()

    expected = recommend_all_modes(
        heroes,
        catalog,
        troops_cfg,
        scenarios,
        event=event_profile,
        troop_stats=troop_stats,
        truegold=int(saved["truegold"]),
        gear=gear_pieces,
        gear_profile="early_game_growth",
    )
    expected_best = max(expected.values(), key=lambda r: r.expected_personal_points)

    assert actual_utility == pytest.approx(expected_best.expected_personal_points)


# --- Optimiser Gear XP spend, layout A (Task 7) -----------------------------
#
# What the planner *does* once it has a reply is executed for real in
# tests/test_heroes_optimiser_gear_xp_js.py. What is left here is the server
# half: the page renders the single column the design asks for, its labels
# come off the same config the search consumes, the POST contract is the one
# the legacy page used, and a run proposes without ever writing gear.json.


def _gear_xp_client(tmp_path: Path, *, with_gear: bool = True) -> TestClient:
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir(parents=True)
    _seed_catalog_heroes(heroes_dir)
    gear_dir = None
    if with_gear:
        gear_dir = tmp_path / "gear"
        gear_dir.mkdir(parents=True)
        GearStore(gear_dir).upsert(
            GearRecord(
                piece_id="p0",
                name="Judicator's Armet",
                troop_type="infantry",
                slot="helmet",
                rarity="mythic",
                enhancement_level=0,
                power=1000,
            )
        )
    return TestClient(create_app(gear_dir, heroes_dir=heroes_dir))


def test_gear_xp_page_is_the_single_column_the_design_asks_for(
    tmp_path: Path,
) -> None:
    """Layout A in order: the screen names itself, then target, then the
    fodder bag, then the run control, then the panel the answer lands in.
    Ordering is asserted on positions rather than mere presence, because
    every one of these strings would still be somewhere in the document if
    the column were shuffled."""
    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    order = [
        '<h1 class="page-title">Gear XP spend</h1>',
        '<h2 class="section-title">Target</h2>',
        'aria-label="Event"',
        '<h2 class="section-title">Fodder bag</h2>',
        'id="fodder-grey"',
        'id="fodder-part_100"',
        'id="run-btn"',
        'id="delta-line"',
        'id="spend-list"',
        'id="leftover-line"',
    ]
    seen = [body.index(needle) for needle in order]
    assert seen == sorted(seen), dict(zip(order, seen))


def test_gear_xp_page_offers_one_box_per_fodder_kind_the_api_accepts(
    tmp_path: Path,
) -> None:
    """Derived, not transcribed: the form's boxes must be exactly the keys
    FodderBag carries, or a kind the user owns has nowhere to be entered."""
    from ks.heroes.optimize.xp_ladder import FodderBag

    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    offered = set(re.findall(r'data-fodder="([a-z0-9_]+)"', body))
    assert offered == set(FodderBag().counts())


def test_gear_xp_fodder_labels_quote_the_configured_xp_values(
    tmp_path: Path,
) -> None:
    """The "30 XP each" note beside a box is read off
    pieces_and_stats.yaml — the same file allocate_fodder_xp() spends
    against — so retuning it cannot leave the form lying to the user."""
    from ks.heroes.optimize.xp_ladder import load_fodder_xp_values

    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    values = load_fodder_xp_values()
    assert set(values) == {"grey", "green", "blue", "purple", "part_100"}
    for kind, xp in values.items():
        label_at = body.index(f'for="fodder-{kind}"')
        field = body[label_at : body.index(f'id="fodder-{kind}"')]
        assert f"{xp} XP each" in field, (kind, field)


def test_gear_xp_mode_pickers_offer_exactly_the_modes_the_solver_has(
    tmp_path: Path,
) -> None:
    """Also derived: the sword and bear pickers are built from the very
    point-scenario files build_event_utility() hands to recommend(), so the
    form can never offer a mode the API would reject."""
    from ks.heroes.optimize.scenarios import load_scenarios

    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    for event, filename in (
        ("swordland", "point_scenarios.yaml"),
        ("beartrap", "point_scenarios_beartrap.yaml"),
    ):
        start = body.index(f'data-mode-select="{event}"')
        block = body[start : body.index("</select>", start)]
        offered = set(re.findall(r'<option value="([a-z_]*)"', block))
        expected = set(load_scenarios(REPO_ROOT / "config" / filename))
        # "" is the "Best mode" option: no `mode` key is sent at all.
        assert offered == expected | {""}, (event, offered)

    # Arena has sides, not scenario modes, and no "let the search pick".
    arena = body[
        body.index('data-mode-select="arena"') : body.index(
            "</select>", body.index('data-mode-select="arena"')
        )
    ]
    assert set(re.findall(r'<option value="([a-z]*)"', arena)) == {"attack", "defense"}


def test_gear_xp_page_keeps_its_spend_list_a_list(tmp_path: Path) -> None:
    """`list-style: none` makes Safari/VoiceOver stop treating an `<ol>` as a
    list, and the *order* of these steps is the answer the page gives — each
    is the best remaining move once the ones above it are paid for. The CSS
    rule that costs the semantics is asserted next to the attribute that
    restores them, so removing either is a failure."""
    c = _gear_xp_client(tmp_path)
    body = c.get("/optimiser/gear-xp").text
    assert '<ol class="spend-list" id="spend-list" role="list">' in body
    css = c.get("/static/app.css").text
    assert "list-style: none" in _css_rule_body(css, ".spend-list {")


def test_gear_xp_page_degrades_when_a_scenario_file_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading the tuning YAML per request is what makes a hand edit show up
    on reload — and unguarded it also meant a typo took the whole screen down
    with a 500, including the fodder boxes and the run button, which have
    nothing to do with the file that broke. Before, the page rendered and only
    the solve failed; that is the behaviour restored here.

    Real broken YAML through the real loader, not a stubbed exception: the
    handler has to survive what the parser actually raises.
    """
    from ks.heroes.ui import app as ui_app

    fake_root = tmp_path / "root"
    (fake_root / "config").mkdir(parents=True)
    (fake_root / "config" / "point_scenarios.yaml").write_text(
        "modes:\n  rally: [oops\n", encoding="utf-8"
    )
    (fake_root / "config" / "point_scenarios_beartrap.yaml").write_text(
        yaml.safe_dump({"modes": {"solo": {"combat_rate": 1.0}}}), encoding="utf-8"
    )
    # REPO_ROOT is also where TroopStore finds its seed, and this test is
    # about the tuning files rather than that one.
    shutil.copyfile(
        REPO_ROOT / "config" / "troops.yaml", fake_root / "config" / "troops.yaml"
    )
    monkeypatch.setattr(ui_app, "REPO_ROOT", fake_root)

    r = _gear_xp_client(tmp_path / "app").get("/optimiser/gear-xp")
    assert r.status_code == 200
    body = r.text

    # The broken half degrades to "Best mode" and nothing else…
    sword_at = body.index('data-mode-select="swordland"')
    sword = body[sword_at : body.index("</select>", sword_at)]
    assert re.findall(r'<option value="([a-z_]*)"', sword) == [""]
    # …the readable half still offers its own modes…
    bear_at = body.index('data-mode-select="beartrap"')
    bear = body[bear_at : body.index("</select>", bear_at)]
    assert "solo" in bear
    # …the page names what it could not read…
    assert 'id="tuning-error"' in body
    assert "Swordland modes" in body and "Bear Trap modes" not in body
    # …and everything that does not depend on that file is untouched.
    assert 'id="run-btn"' in body
    assert body.count('data-fodder="') == 5


def test_gear_xp_page_omits_the_xp_notes_rather_than_500ing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same guard on the third load. `load_fodder_xp_values` reads a path it
    resolves itself, so it is stubbed rather than redirected — the point is
    what the handler does with the raise, not which file it came from.

    An empty "XP each" note is a claim the page cannot back, so the note goes
    away entirely while every box stays.
    """
    from ks.heroes.optimize import xp_ladder

    def unreadable(**_kwargs: Any) -> dict[str, int]:
        raise yaml.YAMLError("could not find expected ':'")

    monkeypatch.setattr(xp_ladder, "load_fodder_xp_values", unreadable)

    r = _gear_xp_client(tmp_path).get("/optimiser/gear-xp")
    assert r.status_code == 200
    body = r.text
    assert "XP each" not in body
    assert body.count('data-fodder="') == 5
    assert 'id="tuning-error"' in body and "fodder XP values" in body


def test_gear_xp_page_carries_no_tuning_banner_when_the_files_are_fine(
    tmp_path: Path,
) -> None:
    """The other half of the two tests above: the notice is conditional, not
    a fixture of the page."""
    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    assert 'id="tuning-error"' not in body


def test_gear_xp_page_ships_no_inline_script_or_style(tmp_path: Path) -> None:
    """Global constraint: every rule lives in app.css and the planner's logic
    in /static/optimiser_gear_xp.js."""
    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    assert "<style" not in body
    assert "style=" not in body
    assert "<script>" not in body
    assert 'src="/static/optimiser_gear_xp.js"' in body


def test_gear_xp_page_says_it_only_proposes(tmp_path: Path) -> None:
    """Propose-only is a plan constraint, not an implementation detail: the
    page has to say so where the user is about to press the button, because
    nothing else on screen distinguishes a proposal from a commit."""
    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    note = body[body.index('id="run-btn"') : body.index('id="spend-status"')]
    assert "Proposals only" in note
    assert "written back to your gear inventory" in note


def test_gear_xp_page_links_on_to_the_lineups_the_spend_changes(
    tmp_path: Path,
) -> None:
    """The soft link the design calls for, inside the result panel: the
    spends are judged by a lineup, and that lineup is the next screen."""
    body = _gear_xp_client(tmp_path).get("/optimiser/gear-xp").text
    result = body[body.index('id="spend-result"') :]
    assert '<a class="result-link" href="/optimiser/events">' in result


def test_gear_xp_page_names_the_inventories_it_would_spend_from(
    tmp_path: Path,
) -> None:
    """Same page-meta line every other screen carries — and here it is both
    directories, since the roster decides the utility and the gear is what
    gets levelled."""
    c = _gear_xp_client(tmp_path)
    body = c.get("/optimiser/gear-xp").text
    assert str(tmp_path / "heroes") in body
    assert str(tmp_path / "gear") in body


def test_gear_xp_form_is_inert_without_a_gear_inventory(tmp_path: Path) -> None:
    """A heroes-only app can still reach this page (the Optimiser tab is
    live), so the form has to explain itself rather than fail on submit with
    the API's `--gear` message."""
    body = _gear_xp_client(tmp_path, with_gear=False).get("/optimiser/gear-xp").text
    assert 'id="gear-missing"' in body
    assert "--gear" in body
    assert 'id="run-btn" disabled' in body
    # Every control, not just the button: a form you can fill but never send
    # is worse than one that is visibly switched off.
    assert body.count(" disabled") == 1 + 3 + 3 + 5  # button, segments, modes, counts
    assert "No gear inventory configured." in body


def test_gear_xp_page_is_reachable_from_its_legacy_url(tmp_path: Path) -> None:
    """The redirect Task 1 added now has somewhere real to land: following
    it end to end must reach the built page, not a stub or a 404."""
    c = _gear_xp_client(tmp_path)
    hop = c.get("/optimize/gear-xp", follow_redirects=False)
    assert hop.status_code == 302
    assert hop.headers["location"] == "/optimiser/gear-xp"
    landed = c.get("/optimize/gear-xp")
    assert landed.status_code == 200
    assert '<h1 class="page-title">Gear XP spend</h1>' in landed.text


# --- POST /api/optimize/gear-xp: contract unchanged -------------------------


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"event": "arena_attack", "grey": -1}, "grey must be non-negative"),
        ({"event": "arena_attack", "green": "many"}, "invalid fodder count for green"),
        ({"event": "arena_attack", "blue": None}, "invalid fodder count for blue"),
        (
            {"event": "arena_attack", "part_100": "3.5"},
            "invalid fodder count for part_100",
        ),
    ],
)
def test_gear_xp_api_rejects_counts_it_cannot_spend(
    tmp_path: Path, body: dict[str, Any], detail: str
) -> None:
    """The counts the form guards client-side are guarded here too — the API
    is reachable without the page. Unchanged by this task; pinned because the
    planner's refusal-to-send behaviour is written against these messages."""
    res = _gear_xp_client(tmp_path).post("/api/optimize/gear-xp", json=body)
    assert res.status_code == 400
    assert res.json()["detail"] == detail


def test_gear_xp_api_says_which_half_of_the_setup_is_missing(
    tmp_path: Path,
) -> None:
    """Two different 400s, and the page shows whichever comes back verbatim:
    no --gear at all, versus a gear directory with nothing in it."""
    no_gear = _gear_xp_client(tmp_path / "a", with_gear=False)
    body = {"event": "arena_attack", "grey": 1}
    res = no_gear.post("/api/optimize/gear-xp", json=body)
    assert res.status_code == 400
    assert res.json()["detail"] == "gear inventory required; start UI with --gear"

    heroes_dir = tmp_path / "b" / "heroes"
    heroes_dir.mkdir(parents=True)
    _seed_catalog_heroes(heroes_dir)
    empty_gear = tmp_path / "b" / "gear"
    empty_gear.mkdir(parents=True)
    (empty_gear / "gear.json").write_text("[]", encoding="utf-8")
    c = TestClient(create_app(empty_gear, heroes_dir=heroes_dir))
    res = c.post("/api/optimize/gear-xp", json=body)
    assert res.status_code == 400
    assert res.json()["detail"] == "gear inventory is empty"


def test_gear_xp_api_rejects_an_event_it_cannot_solve(tmp_path: Path) -> None:
    res = _gear_xp_client(tmp_path).post(
        "/api/optimize/gear-xp", json={"event": "city_attack", "grey": 1}
    )
    assert res.status_code == 400
    assert "unsupported event" in res.json()["detail"]


def test_gear_xp_api_accepts_the_body_the_page_sends_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """Propose-only, checked rather than asserted in prose: the exact body
    the planner builds (event + mode + all five counts) is accepted, and
    gear.json is byte-identical afterwards. A spend that quietly levelled the
    piece it proposed would pass every other test in this file.
    """
    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    _seed_catalog_heroes(heroes_dir)
    gear_dir = tmp_path / "gear"
    gear_dir.mkdir()
    GearStore(gear_dir).upsert(
        GearRecord(
            piece_id="p0",
            name="Judicator's Armet",
            troop_type="infantry",
            slot="helmet",
            rarity="mythic",
            enhancement_level=0,
            power=1000,
        )
    )
    gear_json = gear_dir / "gear.json"
    before = gear_json.read_bytes()

    c = TestClient(create_app(gear_dir, heroes_dir=heroes_dir))
    res = c.post(
        "/api/optimize/gear-xp",
        json={
            "event": "arena",
            # "defense", not the "attack" the arena branch falls back to when
            # no mode is sent: the side below has to be evidence the mode
            # travelled, not evidence of the default.
            "mode": "defense",
            "grey": 4,
            "green": 2,
            "blue": 0,
            "purple": 0,
            "part_100": 0,
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    # Every field the planner reads off the reply.
    assert {
        "event",
        "baseline_utility",
        "best_utility",
        "delta_utility",
        "steps",
        "leftover",
        "best_summary",
    } <= set(payload)
    assert set(payload["leftover"]) == {"grey", "green", "blue", "purple", "part_100"}
    assert payload["best_summary"]["side"] == "defense"

    assert gear_json.read_bytes() == before
    assert GearStore(gear_dir).all_pieces()[0].enhancement_level == 0


def test_gear_xp_api_targets_the_mode_the_page_asked_for(tmp_path: Path) -> None:
    """`mode` is the half of the contract the legacy page could never send.
    Forcing a mode has to change which lineup the utility is measured
    against, or the picker is decoration."""
    c = _gear_xp_client(tmp_path)
    bag = {"grey": 0, "green": 0, "blue": 0, "purple": 0, "part_100": 0}

    best = c.post("/api/optimize/gear-xp", json={"event": "swordland", **bag}).json()
    joiner = c.post(
        "/api/optimize/gear-xp", json={"event": "swordland", "mode": "joiner", **bag}
    ).json()

    assert best["best_summary"]["mode"] != "joiner"
    assert joiner["best_summary"]["mode"] == "joiner"
    assert joiner["baseline_utility"] != best["baseline_utility"]


def test_gear_xp_styles_are_phone_first(tmp_path: Path) -> None:
    css = _client(tmp_path).get("/static/app.css").text

    # Full-width controls in the single column — the design's own wording —
    # rather than the troops editor's label-left/value-right row.
    stack = _css_rule_body(css, "input.stack-input,\nselect.stack-input {")
    assert "width: 100%" in stack
    assert "var(--tap)" in stack

    # `display: grid` on .stack-field beats the UA's `[hidden]` rule, so the
    # two mode pickers that do not apply would stay on screen without this.
    assert "display: none" in _css_rule_body(css, ".stack-field[hidden] {")

    # The primary action is a filled accent pill and spans the column at
    # 390px. Bound to the rule inside the narrow breakpoint specifically:
    # the base .btn-run rule above it would satisfy a looser needle while
    # the responsive one was deleted outright.
    run = _css_rule_body(css, ".btn-run {")
    assert "background: var(--accent)" in run
    assert "var(--tap)" in run
    narrow_at = css.index("@media (max-width: 640px)")
    assert "width: 100%" in _css_rule_body(css[narrow_at:], ".btn-run {")

    # The delta line wraps rather than pushing the page sideways, and long
    # OCR'd piece names break instead of widening the column.
    assert "flex-wrap: wrap" in _css_rule_body(css, ".delta-line {")
    assert "overflow-wrap: anywhere" in _css_rule_body(css, ".spend-name {")


def test_the_two_tap_target_links_share_one_rule(tmp_path: Path) -> None:
    """The Gear XP result's link out is the same control as the inventory
    toolbar's link into the Optimiser, so it reuses that declaration instead
    of copying it. Pinned because a copy is exactly what a later edit would
    reach for, and the two would then drift."""
    css = _client(tmp_path).get("/static/app.css").text
    shared = _css_rule_body(css, ".trust-cta,\n.result-link {")
    assert "min-height: var(--tap)" in shared
    # Comments stripped first: the rule's own comment names both classes, and
    # counting raw occurrences would pass with a second rule sitting below it.
    assert re.sub(r"/\*.*?\*/", "", css, flags=re.S).count(".result-link") == 1


def test_the_busy_run_button_keeps_a_readable_label(tmp_path: Path) -> None:
    """The planner sets `disabled` *and* `.busy` on the one filled control on
    the page, and both shared rules that then apply were written for the
    outline buttons elsewhere: `button.busy` (0,1,1) beats `.btn-run`'s own
    `color` (0,1,0) and paints the label --muted, then `button:disabled` fades
    it to 0.45. That is grey-on-blue at 45% for the whole multi-second solve.

    The two rules that cause it are asserted alongside the override, so this
    fails loudly if the override is deleted *or* if it is left in place after
    the thing it compensates for has changed.
    """
    c = _client(tmp_path)
    css = c.get("/static/app.css").text

    assert "color: var(--muted)" in _css_rule_body(css, "button.busy {")
    assert "opacity: 0.45" in _css_rule_body(css, "button:disabled,")

    # The compound selector specifically: `.btn-run {` would satisfy a looser
    # needle while this rule was gone.
    busy_run = _css_rule_body(css, ".btn-run.busy {")
    assert "color: var(--panel)" in busy_run
    faded = re.search(r"opacity:\s*([\d.]+)", busy_run)
    assert faded is not None and float(faded.group(1)) > 0.45, busy_run

    # …and the class is really put on that button, so the rule is reachable.
    planner = c.get("/static/optimiser_gear_xp.js").text
    assert 'runBtn.classList.toggle("busy"' in planner


def test_both_optimiser_pages_share_one_status_line_writer(tmp_path: Path) -> None:
    """`setStatus` existed twice with the arguments flipped — `(text, kind)`
    on the planner, `(kind, text)` on the board. Both parameters are strings
    and neither copy validated them, so the wrong order raised nothing: it
    wrote the message into the element's class and the state word into its
    text. app.js owns the two lines now.

    Pinned on the `"status-line"` literal, which is what a re-inlined copy
    would have to spell again, and on the argument order of both wrappers.
    """
    c = _client(tmp_path)
    assert "window.setStatusLine" in c.get("/static/app.js").text

    for name in ("optimiser_events.js", "optimiser_gear_xp.js"):
        src = c.get(f"/static/{name}").text
        assert '"status-line"' not in src, name
        assert "window.setStatusLine(statusEl, text, kind)" in src, name
        assert "function setStatus(text, kind)" in src, name


def test_every_grouped_number_in_the_ui_groups_the_same_way(tmp_path: Path) -> None:
    """A bare `toLocaleString()` follows the *browser's* locale, so the same
    1,200 renders "1.200" on one machine and "1 200" on another — and the
    lineup board used to do that while the Gear XP planner and the troops
    editor beside it were pinned to en-US. One rule for the whole bundle,
    checked across every script rather than at the one call site that drifted.

    Comments are stripped first: two of these files explain in prose why the
    bare call is wrong, and that prose must not satisfy the check.
    """
    static_dir = REPO_ROOT / "ks" / "heroes" / "ui" / "static"
    scripts = sorted(static_dir.glob("*.js"))
    assert len(scripts) >= 5, scripts
    calls = 0
    for path in scripts:
        src = path.read_text(encoding="utf-8")
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
        for args in re.findall(r"toLocaleString\(([^)]*)\)", src):
            assert args.strip() == '"en-US"', (path.name, args)
            calls += 1
    assert calls >= 3, calls


# --- Hero levels placeholder + legacy cleanup (Task 8) ----------------------

TEMPLATES_DIR = REPO_ROOT / "ks" / "heroes" / "ui" / "templates"

#: The pre-cutover page templates. Unreferenced since Task 1 moved the IA to
#: /inventory and /optimiser, and each still carried its own inline copy of
#: RARITY_RANK / sortTable / showToast — the duplication Tasks 5 and 6 spent
#: fix waves removing from the live pages. `optimize.html` never existed on
#: this branch; it is listed so the name can never come back either.
LEGACY_TEMPLATES = (
    "gear.html",
    "heroes.html",
    "optimize.html",
    "optimize_hub.html",
    "optimize_events.html",
    "optimize_gear_xp.html",
    "_nav_tabs.html",
)


def test_hero_levels_reserves_the_subtab_in_words(tmp_path: Path) -> None:
    """The third Optimiser tool has no solver on this branch, so the page has
    to say what it will be and why it is empty. An unstyled stub reads as a
    broken screen, and a 404 would have made the third segment a dead
    control."""
    body = _client(tmp_path).get("/optimiser/hero-levels").text
    assert '<h1 class="page-title">Hero levels — coming next</h1>' in body
    assert "Recommend which heroes to push for a chosen event." in body
    assert (
        "Solver design is tracked separately; this subtab reserves the IA."
    ) in body


def test_hero_levels_is_a_placeholder_and_not_a_half_wired_tool(tmp_path: Path) -> None:
    """No form, no page module, no API call — a solver was committed to this
    worktree mid-plan and reverted, and the page must not be a stub of it.
    The only script on the page is the layout's shared helpers."""
    body = _client(tmp_path).get("/optimiser/hero-levels").text
    assert "<form" not in body
    assert re.findall(r'<script src="([^"]+)"', body) == ["/static/app.js"]
    # Same global constraints as every other screen.
    assert "<style" not in body and "style=" not in body and "<script>" not in body
    # Reserved, not stranded: the one control on it goes somewhere that works.
    assert '<a class="result-link" href="/optimiser/events">' in body


def test_the_legacy_page_templates_are_deleted(tmp_path: Path) -> None:
    for name in LEGACY_TEMPLATES:
        assert not (TEMPLATES_DIR / name).exists(), name


def test_nothing_still_names_a_legacy_template() -> None:
    """Word-boundary matched on purpose: `inventory_heroes.html` ends with
    `heroes.html` and `inventory_gear.html` with `gear.html`, so a plain
    substring search would report the live templates as references to the
    dead ones and this check would be unfalsifiable."""
    names = "|".join(re.escape(n) for n in LEGACY_TEMPLATES)
    pattern = re.compile(rf"(?<![\w-])({names})")
    here = Path(__file__).resolve()
    hits: list[str] = []
    for root in (REPO_ROOT / "ks", REPO_ROOT / "tests"):
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".py", ".html", ".js", ".css"}:
                continue
            # This file names them deliberately, in order to look for them.
            if path.resolve() == here:
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO_ROOT)
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{rel}:{lineno}: {line.strip()}")
    assert hits == [], "\n".join(hits)


def test_every_template_is_reached_from_app_py_or_another_template() -> None:
    """Derived, so it keeps working after this task: any template that is
    neither rendered by a route nor pulled in by `extends`/`include` is dead
    code. This is what would have caught the legacy set drifting for seven
    tasks, and what will catch the next one."""
    app_src = (REPO_ROOT / "ks" / "heroes" / "ui" / "app.py").read_text(
        encoding="utf-8"
    )
    reachable = set(re.findall(r'"([a-z0-9_]+\.html)"', app_src))
    for path in TEMPLATES_DIR.glob("*.html"):
        reachable |= set(
            re.findall(
                r'{%-?\s*(?:extends|include)\s+"([^"]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    orphans = sorted(
        p.name for p in TEMPLATES_DIR.glob("*.html") if p.name not in reachable
    )
    assert orphans == []


@pytest.mark.parametrize(
    ("legacy", "marker"),
    [
        ("/gear", 'data-rescan-url="/api/gear/rescan"'),
        ("/heroes", 'data-rescan-url="/api/heroes/rescan"'),
        ("/optimize", '<h1 class="page-title">Event lineups</h1>'),
        ("/optimize/events", '<h1 class="page-title">Event lineups</h1>'),
        ("/optimize/gear-xp", '<h1 class="page-title">Gear XP spend</h1>'),
    ],
)
def test_every_legacy_url_still_lands_on_a_real_page(
    tmp_path: Path, legacy: str, marker: str
) -> None:
    """The templates these URLs used to render are deleted. Following each
    redirect all the way through has to reach a 200 carrying the new screen's
    own markup — the hop alone (asserted above) would still pass if the
    destination had gone down with them."""
    landed = _client(tmp_path).get(legacy)
    assert landed.status_code == 200, legacy
    assert marker in landed.text, legacy


def test_the_console_advertises_the_new_ia_and_only_real_pages(
    tmp_path: Path,
) -> None:
    """`run_ui` prints these on start-up and was the last surface still
    naming /heroes, /optimize and /gear. Those all still redirect, which is
    exactly why nothing else caught it — so the paths are checked against the
    app's own routes and against the legacy set by name."""
    from ks.heroes.ui.app import startup_paths

    legacy = {"/gear", "/heroes", "/optimize", "/optimize/events", "/optimize/gear-xp"}
    c = _client(tmp_path)
    printed = [path for _, path in startup_paths(gear=True, heroes=True)]
    assert printed
    for path in printed:
        assert path not in legacy, path
        assert c.get(path, follow_redirects=False).status_code == 200, path
    # Every screen in the shell except the reserved placeholder, which is
    # reachable in the subnav but is not something to go and do.
    assert set(printed) == set(SHELL_PAGES) - {"/optimiser/hero-levels"}

    # Both capability flags gate what is offered.
    assert [p for _, p in startup_paths(gear=True, heroes=False)] == [
        "/inventory/gear",
        "/inventory/troops",
    ]
    assert "/inventory/gear" not in [
        p for _, p in startup_paths(gear=False, heroes=True)
    ]


def test_run_ui_prints_the_startup_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """And `run_ui` really prints them, rather than keeping a second list.
    uvicorn is stubbed at the module it imports, so nothing binds a port."""
    uvicorn = pytest.importorskip("uvicorn")
    from ks.heroes.ui.app import run_ui, startup_paths

    served: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.update(kw))

    gear = tmp_path / "gear"
    gear.mkdir()
    (gear / "gear.json").write_text("[]", encoding="utf-8")
    heroes = tmp_path / "heroes"
    heroes.mkdir()
    (heroes / "heroes.json").write_text("[]", encoding="utf-8")

    run_ui(gear, heroes_dir=heroes, host="127.0.0.1", port=9999)
    assert served["port"] == 9999  # the stub really stood in for the server

    out = capsys.readouterr().out
    for _, path in startup_paths(gear=True, heroes=True):
        assert f"http://127.0.0.1:9999{path}" in out, path
    # The pre-cutover IA is gone from the console for good.
    for stale in (":9999/gear", ":9999/heroes", ":9999/optimize"):
        assert stale not in out, stale
