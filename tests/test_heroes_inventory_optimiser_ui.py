"""Apple-light Inventory/Optimiser shell: routes, redirects, chrome, CSS."""

from __future__ import annotations

import re
from pathlib import Path

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
