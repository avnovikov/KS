"""Run the Event lineups board's real JavaScript and assert on what it does.

Everything on `/optimiser/events` is drawn in the browser from a single
`GET /api/optimize`: the event segmented control, the mode chips, the
formation board, the hero sheet, the escaping, and every partial-failure
path. A page-render test can only see the empty shell, and a source grep
cannot tell whether any of it works.

So this drives the files for real, exactly the way
`tests/test_heroes_inventory_js.py` drives the inventory table:
`tests/js/optimiser_events_harness.js` stands up a fake DOM and a recordable
`fetch`, the two static files are injected into it verbatim, and the whole
thing runs under whichever JS engine the host happens to have. There is no JS
toolchain in this repo and none is added: if no engine is found the module
skips with a reason.

`app.js` is injected alongside the board because the board depends on it:
`window.escapeHtml` and `window.bindDialogDismiss` live there now, one copy
for this page and `hero_detail.js` both.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "ks" / "heroes" / "ui" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "optimiser_events_harness.js"

#: Engines that run `<engine> [args] file.js` and drain the microtask queue
#: before exiting. jsc ships with macOS but is not on PATH.
_ENGINE_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("node", ()),
    ("bun", ()),
    ("deno", ("run", "--quiet")),
    ("jsc", ()),
    ("qjs", ()),
    ("d8", ()),
)
_JSC_MACOS = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework"
    "/Versions/A/Helpers/jsc"
)

_RESULT_MARKER = "@@RESULTS@@"


def _find_engine() -> list[str] | None:
    for name, args in _ENGINE_CANDIDATES:
        found = shutil.which(name)
        if found:
            return [found, *args]
    if _JSC_MACOS.exists():
        return [str(_JSC_MACOS)]
    return None


def _build_script(tmp_path: Path) -> Path:
    """Splice the two real static files into the harness, verbatim.

    Injection beats `eval` of a read-in string: the sources run as ordinary
    code, so a syntax error in either file is reported at a real line rather
    than swallowed, and nothing about the files has to be JS-escaped.
    """
    harness = HARNESS.read_text(encoding="utf-8")
    injections = (
        ("// @@APP_JS@@", "app.js"),
        ("// @@OPTIMISER_EVENTS_JS@@", "optimiser_events.js"),
    )
    for marker, name in injections:
        assert marker in harness, f"harness lost its {name} injection point"
        source = (STATIC_DIR / name).read_text(encoding="utf-8")
        harness = harness.replace(marker, source)
    script = tmp_path / "optimiser_events_harness.run.js"
    script.write_text(harness, encoding="utf-8")
    return script


@pytest.fixture(scope="module")
def js_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    engine = _find_engine()
    if engine is None:
        pytest.skip(
            "no JavaScript engine on this host — install node (or bun/deno/"
            "qjs), or run on macOS where JavaScriptCore's jsc ships at "
            f"{_JSC_MACOS}. The board's JS is only covered where one exists."
        )
    script = _build_script(tmp_path_factory.mktemp("jsevents"))
    proc = subprocess.run(
        [*engine, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(_RESULT_MARKER)]
    if not lines:
        pytest.fail(
            "the JS harness produced no results.\n"
            f"engine: {engine}\nexit: {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    payload = json.loads(lines[-1][len(_RESULT_MARKER) :])
    payload["engine"] = engine
    return payload


def _failures(js_run: dict, names: list[str] | None = None) -> list[str]:
    wanted = None if names is None else set(names)
    return [
        f"{c['name']}: {c['detail']}"
        for c in js_run["checks"]
        if not c["ok"] and (wanted is None or c["name"] in wanted)
    ]


def _assert_ran(js_run: dict, names: list[str]) -> None:
    """Guard against a check silently disappearing from the harness."""
    present = {c["name"] for c in js_run["checks"]}
    missing = [n for n in names if n not in present]
    assert not missing, f"harness no longer runs: {missing}"
    assert not _failures(js_run, names), "\n".join(_failures(js_run, names))


# --- wiring ------------------------------------------------------------------


def test_board_script_is_served_and_is_the_file_on_disk(tmp_path: Path) -> None:
    """Same wiring check inventory.js and troops.js get: the page's
    `<script src>` resolves, the mount serves it as JavaScript, and the bytes
    on the wire are the same file the JS harness executes — so the two can
    never drift."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.models import HeroRecord
    from ks.heroes.store import HeroStore
    from ks.heroes.ui.app import create_app

    HeroStore(tmp_path).upsert(
        HeroRecord(name="Helga", stars=2, power=1000, scraped_at="t")
    )
    client = TestClient(create_app(heroes_dir=tmp_path))

    page = client.get("/optimiser/events").text
    assert 'src="/static/optimiser_events.js"' in page
    # app.js comes from _layout.html and has to load first: the board reads
    # window.escapeHtml off it at IIFE-evaluation time.
    assert page.index('src="/static/app.js"') < page.index(
        'src="/static/optimiser_events.js"'
    )

    res = client.get("/static/optimiser_events.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
    assert res.text == (STATIC_DIR / "optimiser_events.js").read_text(encoding="utf-8")


def test_the_board_declares_no_second_showtoast_or_escaper(tmp_path: Path) -> None:
    """Task 5 spent a fix wave deleting two local copies of `showToast`, and
    fix wave 1 here deleted two *divergent* copies of `esc` — hero_detail.js
    escaped four characters, this board escaped five. Both helpers now have
    exactly one definition, in app.js, and this pins that no page grows a
    third."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    client = TestClient(create_app(gear_dir=None, heroes_dir=tmp_path))
    app_js = client.get("/static/app.js").text
    board = client.get("/static/optimiser_events.js").text
    hero_detail = client.get("/static/hero_detail.js").text

    assert app_js.count("function esc(") == 1
    for name, source in (("board", board), ("hero_detail", hero_detail)):
        assert "function esc(" not in source, f"{name} redefined esc"
        assert "function showToast" not in source, f"{name} redefined showToast"
        assert "window.escapeHtml" in source, f"{name} does not use the shared esc"

    # The dismiss wiring was the other copy: close button, backdrop-target
    # click and Escape, spelled out identically in both files.
    assert app_js.count("function bindDialogDismiss(") == 1
    for source in (board, hero_detail):
        assert "window.bindDialogDismiss(" in source
        assert 'ev.key === "Escape"' not in source

    # `safeUrl` was the odd one out: the only one of these four that is purely
    # a security control, and the only one still private to a single page
    # script. hero_detail.js did `iconEl.src = hero.icon_url || ""` on the
    # same field the board runs through safeUrl, from the same store, with no
    # check at all — so the branch's one unguarded URL sink was the file that
    # could not see the guard. Pinned on the assignment itself: a revert to
    # the raw field is what this has to catch, and hero_detail.js has no
    # engine harness to catch it at runtime.
    assert app_js.count("function safeUrl(") == 1
    for name, source in (("board", board), ("hero_detail", hero_detail)):
        assert "function safeUrl(" not in source, f"{name} redefined safeUrl"
        assert "window.safeUrl" in source, f"{name} does not use the shared safeUrl"
    assert "var iconSrc = safeUrl(hero.icon_url);" in hero_detail
    assert "iconEl.src = iconSrc;" in hero_detail
    assert "hero.icon_url ||" not in hero_detail


def test_both_optimiser_pages_read_one_error_envelope(tmp_path: Path) -> None:
    """The Gear XP planner unwrapped FastAPI's `{"detail": ...}`; the board
    did `res.text()` and showed the body raw. One reading now, in app.js,
    including the part that is easy to lose — a validation 422 puts a *list*
    of objects in `detail`, and "[object Object]" is worse than useless.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    client = TestClient(create_app(gear_dir=None, heroes_dir=tmp_path))
    app_js = client.get("/static/app.js").text
    assert app_js.count("function detailOf(") == 1
    assert 'typeof detail === "string"' in app_js

    for name in ("optimiser_events.js", "optimiser_gear_xp.js"):
        src = client.get(f"/static/{name}").text
        assert "window.detailOf(" in src, name
        assert 'typeof detail === "string"' not in src, f"{name} re-reads the envelope"


# --- behaviour ---------------------------------------------------------------


def test_board_js_runs_under_a_real_engine(js_run: dict) -> None:
    """Sanity floor: the source parsed and every suite reached its end."""
    assert len(js_run["checks"]) >= 130, len(js_run["checks"])
    assert not _failures(js_run, ["harness ran to completion"])


def test_board_js_every_behavioural_check(js_run: dict) -> None:
    """Every check in the harness, reported together."""
    failures = _failures(js_run)
    assert not failures, "\n".join(
        [f"{len(failures)}/{len(js_run['checks'])} JS checks failed:", *failures]
    )


def test_the_page_draws_itself_from_one_api_call(js_run: dict) -> None:
    """`GET /api/optimize` computes sword, bear and both arena sides in one
    go — several seconds of ILP. So the page fetches once and every event and
    mode switch is served from that bundle; a per-screen refetch would make
    tapping a chip cost a full re-solve."""
    _assert_ran(
        js_run,
        [
            "the board loads itself from /api/optimize",
            "and asks for a fresh answer rather than a cached one",
            "Swordland is the event the page opens on",
            "switching modes costs no extra request — one bundle serves every screen",
            "still without refetching",
        ],
    )


def test_mode_chips_carry_their_points_and_drive_the_board(js_run: dict) -> None:
    _assert_ran(
        js_run,
        [
            "one chip per mode of that event",
            "the first mode is selected for the user",
            "and says so for assistive tech",
            "each chip carries its own points",
            "the chip names the mode, underscores unpicked",
            "the board titles the selected mode, not just the event",
            "tapping a chip moves the board to that mode",
            "and moves the selection with it",
            "the chip that lost it says so too",
            "and the board shows that mode's heroes",
            "tapping Bear Trap switches event",
            "the event segment is marked selected",
            "and the one it left is not",
            "its own modes replace the chips",
            "going back restores the mode that was picked, not the first one",
        ],
    )
    assert "pts" in js_run["data"]["first_chip_html"]


def test_the_board_keeps_troops_and_points_on_it(js_run: dict) -> None:
    """Step 4 of the brief's layout: troops + points meta on the board."""
    _assert_ran(
        js_run,
        [
            "the board meta carries the points",
            "and the troops line the brief asks for",
            "and the points breakdown behind them",
        ],
    )
    meta = js_run["data"]["sword_board_meta"]
    for needle in ("pts", "I ", "C ", "A ", "cap"):
        assert needle in meta, meta


def test_non_arena_modes_march_and_arena_keeps_front_and_back(
    js_run: dict,
) -> None:
    """The two board shapes the brief specifies. Sword/Bear rows carry no
    `formation` at all — three heroes in one line — while arena rows do, and
    the Front/Back split has to survive a 390px viewport, so it is structural
    rather than a wide-screen luxury."""
    _assert_ran(
        js_run,
        [
            "a non-arena mode is one row, not a Front/Back split",
            "labelled March",
            "holding the mode's three heroes in order",
            "arena keeps a Front row and a Back row",
            "named Front and Back",
            "Front holds F1 and F2",
            "Back holds B1..B3",
            "the defense side is its own board",
            "with its own formation",
            "arena chips are the two sides",
            "carrying a score rather than points",
            "attack is the side the board opens on",
            "the meta is the side's score",
        ],
    )
    assert js_run["data"]["arena_back_row"] == "B1=Chenko,B2=Jabel,B3=Diana"


def test_a_hero_is_a_button_with_a_portrait_that_can_fail(js_run: dict) -> None:
    """Only 15 of the roster have artwork in /static/heroes, so a missing
    portrait is the normal case, not an edge one: the initials underneath are
    what the slot falls back to instead of the browser's broken-image glyph."""
    _assert_ran(
        js_run,
        [
            "every hero is a real button, so it is reachable without a pointer",
            "and is labelled for a screen reader",
            "portraits come from /static/heroes/<slug>.webp",
            "with initials underneath for a hero with no artwork",
            "a portrait that fails to load is dropped rather than left as a broken image",
            "an icon URL the API supplies wins over the static slug path",
            "but only if it is one the page would serve",
        ],
    )


def test_tapping_a_hero_opens_the_why_and_gear_sheet(js_run: dict) -> None:
    """The drilldown the legacy page put behind a whole-lineup modal: one
    hero, their solver reasoning, what dropping them would cost, and the four
    gear slots — including the ones with nothing in them."""
    _assert_ran(
        js_run,
        [
            "the sheet starts closed",
            "tapping a hero opens it",
            "titled with the hero",
            "sub-titled with the lineup it came from",
            "the close button takes focus, so the keyboard lands inside the sheet",
            "the why block explains the role",
            "and lists why the solver picked this hero",
            "and what dropping them would cost",
            "the gear grid names all four slots",
            "an assigned piece is named",
            "with its rarity, enhancement, mastery and power",
            "and its icon",
            "an unassigned slot reads Empty rather than being omitted",
            "Close closes it",
            "a second hero reopens it with their own detail",
            "a hero with no gear assigned still gets the four empty slots",
            "Escape closes it",
            "a tap inside the sheet does not dismiss it",
            "a tap on the backdrop does",
            "an arena hero's sheet names their formation slot",
            "and their arena reasoning, scored rather than pointed",
        ],
    )


def test_the_other_two_leave_one_out_verdicts_are_rendered(js_run: dict) -> None:
    """`explain.py` can answer a leave-one-out three ways: a marginal cost, a
    `critical` hero the lineup cannot do without, or `inconclusive` when the
    re-solve did not settle. Only the first was reachable from any fixture,
    so two of `renderWhy`'s three branches went unexecuted — and "critical"
    is the one a user must not miss."""
    _assert_ran(
        js_run,
        [
            "a hero the lineup cannot do without is called out by name",
            "in the critical style, not the ordinary cost line",
            "and without inventing a cost the solver never computed",
            "an inconclusive leave-one-out says so rather than reading as free",
            "carrying the solver's status, escaped like everything else it returns",
            "a formation slot is shown even when the solver named no role",
        ],
    )


def test_everything_from_the_api_is_escaped_before_it_becomes_markup(
    js_run: dict,
) -> None:
    """Hero names, mode keys, gear names and solver strings all originate in
    config files and OCR, and two of the board's renderers assemble markup
    from them by hand. A name like `<img src=x onerror=...>` must come out as
    text everywhere it lands — in a chip, in a slot, in the sheet — and an
    icon URL that is not same-origin must not be rendered at all.
    """
    _assert_ran(
        js_run,
        [
            "a hostile mode name cannot break out of the chip markup",
            "it is escaped instead",
            "a hostile hero name still renders as a slot",
            "and lands as text, never as markup",
            "the portrait URL is slugified, not interpolated raw",
            "the sheet escapes the hero's bullets",
            "keeping the text visible in escaped form",
            "and escapes a hostile gear name",
            "a javascript: icon URL is dropped rather than rendered",
            "the hero's own name in the sheet title is text, not markup",
            "a hostile solver status cannot break out of the chip either",
            "a protocol-relative icon URL is refused",
            "so is its backslash spelling, which a browser parses the same way",
            "and an absolute off-site URL, since every icon the app makes is a path",
            "a same-origin path that would close the src attribute is escaped, not waved through",
            "so no onerror handler ever reaches the markup",
            "an entity-spelled quote in a URL cannot re-open the attribute it sits in",
            "and a bare & in a name is escaped rather than starting an entity",
        ],
    )
    # Spelled out here as well, so the escaping cannot regress to "the string
    # is absent because the render failed".
    chip = js_run["data"]["hostile_chip_html"]
    assert "&quot;" in chip and 'onmouseover="' not in chip, chip
    body = js_run["data"]["hostile_sheet_body"]
    assert "&lt;b&gt;reasons&lt;/b&gt;" in body, body
    assert "javascript:" not in body, body

    # The attribute case, spelled out here too. `safeUrl` is an *origin*
    # check: `/x.png" onerror="alert(1)` passes it (it is a same-origin
    # path), so `esc()` is the only thing between it and a working handler.
    # Removing `esc(url)` from renderGearGrid left all 121 checks of the
    # previous wave green — hence this.
    gear = js_run["data"]["hostile_gear_html"]
    assert 'src="/x.png&quot; onerror=&quot;alert(1)"' in gear, gear
    assert 'onerror="' not in gear, gear
    assert "evil.example" not in gear, gear

    # `&` is the fifth replacement and the only one nothing defended:
    # dropping it from app.js's esc killed 0 of 454 checks. It is also what
    # re-enables the other four — an attacker who cannot write `"` writes
    # `&quot;`, and the browser decodes it back to a quote while parsing the
    # attribute. So the ampersand has to survive as `&amp;`.
    amp = js_run["data"]["ampersand_gear_html"]
    assert 'src="/x.png&amp;quot; onerror=&amp;quot;alert(1)"' in amp, amp
    assert "&quot; onerror=" not in amp, amp


def test_a_failed_section_is_named_rather_than_blanking_the_page(
    js_run: dict,
) -> None:
    """run_optimize_bundle isolates a section failure on purpose — sword can
    die while bear and arena are fine — so the page has to keep the working
    sections usable and say what went wrong on the broken one."""
    _assert_ran(
        js_run,
        [
            "a failed section is named, not blanked",
            "with the solver's own message",
            "its chips are gone",
            "and the board says so rather than showing a stale lineup",
            "the status line reports the error",
            "naming the section",
            "the sections that did work are still usable",
            "and their banner is cleared",
            "a broken arena side is still listed",
            "and flagged on its chip",
            "the chip says what state it is in instead of a fake score",
            "the working side is unaffected",
            "selecting it shows the reason",
            "and no hero slots",
            "the banner names the side",
        ],
    )


def test_warnings_and_skipped_modes_are_surfaced_separately(js_run: dict) -> None:
    """A warning (gear icons unavailable) is not an error, and a mode the ILP
    found infeasible is neither — but a mode that quietly vanished from the
    chip row looks like a bug in the optimiser."""
    _assert_ran(
        js_run,
        [
            "a warning is surfaced",
            "as a warning, not an error",
            "infeasible modes are named rather than silently missing",
            "listing each one",
            "and the note clears on an event that skipped nothing",
            "no section error banner on a clean bundle",
            "and no skipped-modes note",
            "the status line reports success",
            "and says what it recomputed from",
        ],
    )


def test_a_failed_request_is_reported_and_retryable(js_run: dict) -> None:
    """The board was the one of five fetch callers that did `res.text()` and
    put the body on screen unread, and the harness fixture hid it by replying
    with a bare string where FastAPI sends `{"detail": "..."}`. Latent rather
    than live — an unhandled exception answers in plain text, and the
    JSON-envelope 404 only fires when heroes are unconfigured, in which case
    the page 404s too — but user-visible the first time /api/optimize grows an
    HTTPException, which the two rescan endpoints already have.
    """
    _assert_ran(
        js_run,
        [
            "a failed request surfaces the server's reason",
            "unwrapped from the JSON envelope, not printed as the raw body",
            "a non-string detail is never printed as [object Object]",
            "as an error",
            "and raises it through the shared toast",
            "the board is left empty rather than half-drawn",
            "Regenerate retries",
            "and a later success replaces the error",
            "clearing the status",
        ],
    )


def test_regenerate_locks_out_a_second_recompute_while_one_is_in_flight(
    js_run: dict,
) -> None:
    """`/api/optimize` runs several ILPs; letting a second one start while
    the first is open would double the wait and race two renders."""
    _assert_ran(
        js_run,
        [
            "the control is usable once loaded",
            "a recompute in flight disables the control",
            "and says so on the status line",
            "without firing a second request",
            "finishing re-enables it",
            "and so does failing",
            "which is reported, not swallowed",
            # The lockout is on [data-regen] only — the board itself must
            # stay usable, and the answer must not undo a choice made while
            # it was in the air.
            "the board still switches mode while a refresh is open",
            "and the arriving bundle keeps the mode chosen during the wait",
        ],
    )


def test_portrait_slugs_agree_with_the_python_that_named_the_files(
    js_run: dict,
) -> None:
    """`/static/heroes/<slug>.webp` is written by
    `ks/heroes/ui/hero_icons.py:hero_slug`, and the board re-derives the same
    slug in JS because `/api/optimize` returns hero *names*, not icon URLs.
    Two implementations of one rule: if they drift, every portrait silently
    falls back to initials and nothing else notices.
    """
    from ks.heroes.ui.hero_icons import hero_slug

    _assert_ran(
        js_run,
        [
            "every hero in the lineup gets a portrait URL",
            "a name that slugifies to nothing still resolves somewhere",
            "a two-word name takes one initial from each word",
            "punctuation does not shift which letters those are",
            "and a one-word name takes its first two letters",
        ],
    )
    urls = json.loads(js_run["data"]["slug_urls"])
    assert len(urls) >= 7, urls
    for name, url in urls.items():
        assert url == f"/static/heroes/{hero_slug(name)}.webp", name


def test_tab_newline_and_cr_cannot_smuggle_an_off_site_portrait(
    js_run: dict,
) -> None:
    """`safeUrl` rejected `//host/x` and its backslash spelling but admitted
    `/<tab>/host/x`. Browsers strip ASCII tab, LF and CR from a URL *before*
    parsing it, so what is actually fetched is `//host/x` — the exact case the
    function exists to refuse. Reproduced under jsc before the fix: all three
    spellings came back unchanged.
    """
    _assert_ran(
        js_run,
        [
            "a protocol-relative URL hidden behind a tab is refused",
            "a protocol-relative URL hidden behind a newline is refused",
            "a protocol-relative URL hidden behind a carriage return is refused",
            "while an ordinary same-origin path with no separator is still served",
        ],
    )


def test_the_boards_grouped_numbers_pin_their_locale(js_run: dict) -> None:
    """`fmtPoints` is one of four `toLocaleString` call sites in this UI and
    only the troops editor's was defended: delocalising this one killed 0 of
    138 checks. The harness swaps `Number.prototype.toLocaleString` for a
    sentinel that fires when the locale argument is omitted, so the check is
    about what the *source* passes rather than about the host's own locale
    happening to be en-US.
    """
    _assert_ran(
        js_run,
        ["the board pins its grouping instead of following the viewer's locale"],
    )
    assert "LOCALE-DEFAULT" not in js_run["data"]["locale_rendered"]


def test_degenerate_bundles_do_not_render_a_broken_board(js_run: dict) -> None:
    _assert_ran(
        js_run,
        [
            "an event with no feasible mode shows no chips",
            "and says so on the board instead of rendering nothing",
            "with no section-error banner, because nothing failed",
            "a hole in the formation still renders its slot",
            "marked empty",
            "and not clickable",
        ],
    )
