"""Run the inventory table's real JavaScript and assert on what it does.

`ks/heroes/ui/static/inventory.js` carries the whole client side of the
Spreadsheet+ tables — the per-row save state machine (debounce, dedupe,
in-flight coalescing, blank/blur handling, range validation), the trust-flag
lifecycle across `sessionStorage`, the filter chips and the sort. None of that
is observable from a page-render test, and a source-substring grep cannot tell
whether any of it *works*.

So this drives the files for real, exactly the way
`tests/test_heroes_troops_editor_js.py` drives the troops editor:
`tests/js/inventory_harness.js` stands up a fake DOM, a controllable clock and
a recordable `fetch`, the two static files are injected into it verbatim, and
the whole thing runs under whichever JS engine the host happens to have. There
is no JS toolchain in this repo and none is added: if no engine is found the
module skips with a reason.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "ks" / "heroes" / "ui" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "inventory_harness.js"

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
        ("// @@INVENTORY_JS@@", "inventory.js"),
    )
    for marker, name in injections:
        assert marker in harness, f"harness lost its {name} injection point"
        source = (STATIC_DIR / name).read_text(encoding="utf-8")
        harness = harness.replace(marker, source)
    script = tmp_path / "inventory_harness.run.js"
    script.write_text(harness, encoding="utf-8")
    return script


@pytest.fixture(scope="module")
def js_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    engine = _find_engine()
    if engine is None:
        pytest.skip(
            "no JavaScript engine on this host — install node (or bun/deno/"
            "qjs), or run on macOS where JavaScriptCore's jsc ships at "
            f"{_JSC_MACOS}. The table's JS is only covered where one exists."
        )
    script = _build_script(tmp_path_factory.mktemp("jsinventory"))
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


def test_inventory_js_runs_under_a_real_engine(js_run: dict) -> None:
    """Sanity floor: the source parsed and every suite reached its end."""
    assert len(js_run["checks"]) >= 60, len(js_run["checks"])
    assert not _failures(js_run, ["harness ran to completion"])


def test_the_debounce_is_actually_400ms(js_run: dict) -> None:
    """The harness's fake clock used to discard `setTimeout`'s delay, so the
    interval the brief specifies was asserted by nothing: raising
    `DEBOUNCE_MS` to 30 seconds left every check green. The clock records the
    delay now, and this pins the number on both sides — in JS, and here.
    """
    _assert_ran(js_run, ["and schedules it at the 400ms the brief specifies"])
    assert js_run["data"]["debounce_delays"] == "400"


def test_inventory_js_every_behavioural_check(js_run: dict) -> None:
    """Every check in the harness, reported together."""
    failures = _failures(js_run)
    assert not failures, "\n".join(
        [f"{len(failures)}/{len(js_run['checks'])} JS checks failed:", *failures]
    )


def test_autosave_debounces_and_sends_the_whole_row(js_run: dict) -> None:
    """The brief's contract: `input` debounce 400ms -> PATCH, no Save button.

    The row's whole editable state goes in every request, so what the store
    holds for a row is always exactly what that row shows — a partial body
    would let the two drift the moment two boxes were edited in one debounce
    window.
    """
    _assert_ran(
        js_run,
        [
            "the rendered table fires no PATCH on load",
            "typing schedules a save instead of sending one",
            "the debounce fires exactly one PATCH",
            "it is a JSON PATCH to the row's own API URL",
            "the request is not cached",
            "keepalive is set so a save survives navigation",
            "it sends the row's whole editable state, not just the box that moved",
            "blurring an unchanged row does not re-PATCH",
            "the power cell is refreshed from the server's answer",
            "and so is the row's sort key, so a re-sort orders by what is on screen",
            "pagehide flushes a pending debounce",
        ],
    )


def test_a_blank_box_never_becomes_a_null_the_api_rejects(js_run: dict) -> None:
    """Task 3 hit this on the troops form: a cleared numeric input serializes
    to JSON null and the API 422s it. Here the two endpoints *do* have an
    "unknown" state, so the rule is different but the invariant is the same —
    nothing is sent while the box is empty, and what is stored on blur equals
    what is shown. Gear spells it `clear_enhancement`/`clear_mastery`; heroes
    spell it as an explicit `null` for `stars`/`pellets`.
    """
    _assert_ran(
        js_run,
        [
            "a cleared box schedules nothing while it is empty",
            "and does not nag mid-typing",
            "blurring a cleared box sends the API's own clear flag",
            "and the box stays empty rather than being filled in with a guess",
            "no bare null reaches a gear PATCH",
            "a blank hero star box is sent as an explicit null, the API's own spelling",
        ],
    )
    # Spelled out whole, not by membership: the row's *entire* editable state
    # goes in every body, so this also pins that adding the rarity/slot
    # pickers did not quietly change how the other four columns serialize.
    assert json.loads(js_run["data"]["gear_clear_body"]) == {
        "slot": "helmet",
        "rarity": "mythic",
        "enhancement_level": 52,
        "clear_mastery": True,
    }
    assert json.loads(js_run["data"]["heroes_clear_body"]) == {
        "level": 40,
        "stars": None,
        "pellets": 0,
    }


def test_out_of_range_values_never_leave_the_page(js_run: dict) -> None:
    """`min`/`max` come from the template and mirror the API's own bounds.
    A prefix of a valid number is always in range for these columns (0..200,
    0..20, 0..5), so debounced typing cannot produce a rejected intermediate —
    but a genuinely out-of-range value has to be caught here, named, and not
    sent."""
    _assert_ran(
        js_run,
        [
            "a value over max is not sent",
            "still not sent on blur",
            "the error names the field and the bound",
            "the field is marked invalid for assistive tech",
            "typing again stops nagging immediately",
            "fixing it clears the flag and saves",
            "a server error is surfaced verbatim",
        ],
    )


def test_reverting_an_edit_during_an_in_flight_patch_is_not_dropped(
    js_run: dict,
) -> None:
    """Regression, ported from the bug Task 3 shipped and then fixed: save()
    must test `saving` *before* deduping.

    `lastSavedBody` is only refreshed on success, so mid-flight it still
    describes the pre-save row. Deduping first meant that typing a value,
    blurring, then typing the *previous* value back and blurring again while
    the first PATCH was still open returned early without queueing — the first
    PATCH then landed and recorded the value the user had just undone, leaving
    the row showing one number and the store holding another.
    """
    _assert_ran(
        js_run,
        [
            "an edit starts a PATCH",
            "the revert is held, not sent, while a PATCH is in flight",
            "the revert is not dropped: it goes out once the first PATCH lands",
            "the last thing the server was told is the value on screen",
        ],
    )
    data = js_run["data"]
    # Spelled out so this cannot pass by never entering the in-flight path.
    assert data["race_calls_after_edit"] == 1
    assert data["race_calls_during_flight"] == 1, "the second save was not held"
    assert data["race_calls_after_release"] == 2, "the queued save never ran"
    assert data["race_displayed"] == data["race_server"], (
        f"row shows {data['race_displayed']}, server holds {data['race_server']}"
    )


def test_concurrent_saves_coalesce_per_row_but_not_across_rows(
    js_run: dict,
) -> None:
    """Each row is its own state machine: edits to one row queue behind that
    row's in-flight PATCH, while a *different* row saves straight away. A
    single table-wide lock would serialize a bulk edit pass into one request
    per debounce, which is the whole workflow this page exists for."""
    _assert_ran(
        js_run,
        [
            "the first edit is in flight",
            "further edits queue behind it rather than racing it",
            "several edits during one save coalesce into exactly one more PATCH",
            "carrying the final value, not an intermediate one",
            "and the queue drains rather than looping",
            "a different row saves concurrently instead of queueing behind the first",
            "a response landing mid-typing does not clobber the box",
        ],
    )


def test_a_rejected_save_leaves_a_mark_that_outlives_its_toast(
    js_run: dict,
) -> None:
    """A failed write used to be reported only by a toast that clears itself
    after ~6 seconds. The box kept the rejected value, the row looked normal,
    `lastSavedBody` stayed stale, and `blur` never fires again on a field the
    user has already left — so an edit could be lost with nothing on screen
    saying so. Removing the per-row Save button is exactly what made that
    dangerous: with a button, the user's attention was on the row when the
    write failed.

    The row now carries `data-unsaved` until a save for it actually succeeds,
    joins the "Needs attention" filter so it stays findable, and the failed
    body is not recorded as saved so a later edit really does retry. The
    per-input flag still clears on the next keystroke — the page must not nag
    while the user is fixing it — which is why the persistent half lives on
    the row.
    """
    _assert_ran(
        js_run,
        [
            "a rejected PATCH marks the row unsaved",
            "and flags the box the user just left for assistive tech",
            "the box keeps what the user typed rather than silently reverting",
            "the mark outlives the toast that carried the reason",
            "a row the server rejected shows up under Needs attention",
            "re-blurring the rejected value retries it rather than deduping against a body that never landed",
            "a successful save clears the unsaved mark",
            "and drops the row back out of Needs attention",
            "a client-side range error also marks the row unsaved",
            "typing clears the per-box nag straight away",
            "but the row still says it has not saved",
            "until the fix actually reaches the server",
        ],
    )
    assert js_run["data"]["rejected_row_state"] == "1"


def test_undoing_a_rejected_edit_clears_the_unsaved_mark(js_run: dict) -> None:
    """The mark has to end when the divergence ends, and the normal way it
    ends is an undo: type 999, be told it is out of range, put the old number
    back. That path sends nothing — `body === lastSavedBody` returns early —
    so the success path never runs and the early return is the only place
    that can notice the row now equals what the server last confirmed.

    Left unhandled, the row stayed pink with its red sticky bar and stayed
    pinned in "Needs attention" until a reload. A permanently stuck false
    error is worse than the transient toast it replaced, on a page whose
    entire job is trust signalling — and it pollutes the review pass the
    chip exists for. Covered on both paths that set the mark: a server
    rejection, and a value the client refuses to send.
    """
    _assert_ran(
        js_run,
        [
            "a fresh rejection re-marks the row",
            "undoing a rejected edit sends nothing, because the row already matches",
            "screen and store agree again after an undo, so the unsaved mark clears",
            "and the undone row is not stuck in Needs attention",
            "a fresh range error re-marks the row",
            "undoing an out-of-range value sends nothing either",
            "and clears the mark it set, rather than stranding the row",
        ],
    )
    assert js_run["data"]["after_undo_unsaved"] == "undefined"


def test_sortable_headers_are_operable_from_the_keyboard(js_run: dict) -> None:
    """A `<th>` has no built-in activation behaviour, so click-only headers
    are unreachable without a pointer. They stay columnheaders rather than
    becoming `role="button"` — `aria-sort` is only meaningful on a
    columnheader — with `tabindex="0"` from the template and Enter/Space
    wired here. Space is prevented, or activating a header scrolls the page.
    """
    _assert_ran(
        js_run,
        [
            "Enter sorts a header from the keyboard",
            "so does Space",
            "and both suppress the browser's default",
            "an unrelated key does nothing",
        ],
    )


def test_trust_flags_are_cleared_in_storage_not_only_in_the_dom(
    js_run: dict,
) -> None:
    """The payload has to outlive the render it was applied to: the user
    spot-checks a rescan over several minutes and may reload. So a reviewed
    row's flag is deleted from the sessionStorage payload, the counts are
    re-derived from the remaining map, and the key is removed once the map is
    empty. Clearing only the DOM would resurrect every flag on reload.
    """
    _assert_ran(
        js_run,
        [
            "row classes come from the stored rescan payload",
            "every flagged row is marked",
            "the banner reports the counts of the rows actually on the page",
            "the banner is un-hidden before its text is written",
            "a flag for a row that is no longer on the page is dropped, not counted",
            "the reviewed row loses its class",
            "a successful PATCH clears that row's flag in sessionStorage, not just the DOM",
            "and leaves the other rows' flags alone",
            "the stored counts are re-derived so they still tally the map",
            "the banner counts drop as rows are reviewed",
            "a rejected PATCH leaves the row flagged",
            "reviewing the last flagged row clears the stored payload entirely",
            "and the banner goes away",
        ],
    )
    stored = json.loads(js_run["data"]["trust_after_one_review"])
    assert "cell0" not in stored["flags"]
    assert stored["changed"] == 0
    assert (
        stored["new"] + stored["changed"] + stored["incomplete"]
        == len(stored["flags"])
    )


def test_mark_all_reviewed_clears_the_whole_payload(js_run: dict) -> None:
    _assert_ran(
        js_run,
        [
            "the banner starts visible",
            "Mark all reviewed clears every row class",
            "and the stored payload",
            "and hides the banner",
            "without sending anything to the API",
        ],
    )


def test_needs_attention_survives_a_page_load_with_no_rescan_payload(
    js_run: dict,
) -> None:
    """Incompleteness is stamped server-side by trust.py's own predicate and
    re-derived from `data-required` after each save, so the chip means
    something on an ordinary visit — not only in the minutes after a rescan.
    An incompleteness the page cannot fix (a hero with no power) must survive
    an edit to the fields that *are* editable."""
    _assert_ran(
        js_run,
        [
            "a row whose required box is blank is marked incomplete",
            "a blank box on a row that does not require it is not incomplete",
            "filling one of two required boxes leaves the row incomplete",
            "filling the last required box clears the mark",
            "clearing a required box marks the row incomplete again",
            "an incompleteness the page cannot fix survives an edit",
        ],
    )


def test_filter_chips_and_search_narrow_the_table(js_run: dict) -> None:
    """Filtering is re-applied on chip/search interaction, not after every
    save — a row must not vanish from under the thumb the instant its
    auto-save lands."""
    _assert_ran(
        js_run,
        [
            "All shows every row",
            "and says nothing about a count it is not filtering",
            "Needs attention keeps the trust-flagged row and the incomplete one",
            "the chip is marked pressed",
            "and the previous chip is not",
            "the count reports the filtered subset",
            "a troop chip keeps only that troop",
            "search and chip combine",
            "a search that matches nothing under the active chip shows the empty state",
            "the search survives switching chips",
            "and the empty state is gone",
            "clearing the search restores every row",
            "a row reviewed while filtered stays on screen until the filter is re-applied",
            "and drops out once it is",
        ],
    )
    assert js_run["data"]["attention_visible"] == "cell0,cell2"


def test_sorting_is_shared_between_both_tables(js_run: dict) -> None:
    """One rank table now, not one per page — the two inline copies had
    already drifted (only the heroes one knew "legendary")."""
    _assert_ran(
        js_run,
        [
            "clicking a header sorts ascending",
            "and marks aria-sort",
            "clicking again reverses it",
            "and flips aria-sort",
            "an unknown number sorts below every real value",
            "only the active column carries aria-sort",
            "rarity sorts by rank, not alphabetically",
            "editing a cell keeps the sort key in step",
            "so the re-sort orders by what is on screen",
        ],
    )
    # blue(3) < mythic(5): rank order, not "blue" < "mythic" by luck of the
    # alphabet — cell1 is blue, cell0 and cell2 are both mythic.
    assert js_run["data"]["rarity_order"].split(",")[0] == "cell1"


def test_rescan_stores_the_trust_payload_before_it_navigates(
    js_run: dict,
) -> None:
    """The whole reason HeroesTrust exists: a successful rescan reloads the
    page, which discards every JS variable. If the save happened after
    `location.replace` — or not at all — the next render would show no banner
    and no row cues, and the rescan diff the server computed would be lost.
    """
    _assert_ran(
        js_run,
        [
            "the destructive rescan asks first",
            "declining it sends nothing",
            "and leaves the button alone",
            "a rescan POSTs to the declared endpoint",
            "the rescan's trust payload is stored verbatim for the next render",
            "and stored before the page navigates, or the reload would discard it",
            "the page lands on the declared URL with the server's cache-bust",
            "a failed rescan surfaces the reason",
            "and re-enables the button",
            "restoring its label",
            "and navigates nowhere",
            "the heroes rescan does not ask for confirmation",
        ],
    )
    sequence = js_run["data"]["rescan_sequence"]
    assert sequence.index("store:heroesUiTrust:gear") < sequence.index("navigate")


def test_the_gear_pickers_behave_like_the_boxes_beside_them(js_run: dict) -> None:
    """Rarity and slot came back from the pre-merge page as `<select>`s, and
    a select is the one control here whose *blank* is a chosen value: "—" is
    the release action, so it has to go out on `change` rather than wait for
    a blur that a tap-and-look-away never produces. Everything else — the
    400ms debounce, the whole-row body, the `data-unsaved` mark on a
    rejection — is deliberately identical to the numeric columns.

    The "never mistaken for an out-of-range number" check is the one that
    would otherwise be invisible: `readInt("mythic")` is null, so without the
    picker branch in `isUnsendable` every save on a gear row would be refused
    before it was built.
    """
    _assert_ran(
        js_run,
        [
            "the rarity column is a picker, not a typed box",
            "changing it sends nothing yet",
            "and is debounced on the same 400ms the boxes use",
            "the chosen value goes out as the API's own string",
            "alongside the rest of the row, exactly as a box edit would",
            "the sortable column follows the picker",
            "and so does the rarity tint the column has always had",
            "choosing — sends straight away rather than waiting for a blur",
            "as the API's own clear flag, never an empty string",
            "a picker is never mistaken for an out-of-range number",
            "a rejected picker save marks the row unsaved like any other",
            "and the toast carries the server's reason",
        ],
    )
    # Whole bodies, not membership: the picker columns joined the row's
    # editable state and must serialize as the API spells them.
    assert json.loads(js_run["data"]["picker_body"]) == {
        "slot": "helmet",
        "rarity": "epic",
        "enhancement_level": 51,
        "mastery_level": 2,
    }
    assert json.loads(js_run["data"]["picker_clear_body"]) == {
        "clear_slot": True,
        "rarity": "epic",
        "enhancement_level": 51,
        "mastery_level": 2,
    }


def test_the_pin_tracks_the_store_and_not_the_box(js_run: dict) -> None:
    """The lock model has no flag to read. `GearStore` and `HeroStore` refuse
    to let a rescan change slot/rarity/enhancement/mastery/level while the
    field holds a value, so "pinned" is exactly "the stored value is not
    None", and emptying the field is the only release there is.

    Which is why the pin is painted from the record the server echoes back
    and never from the control: those two disagree precisely when it matters.
    A clear the store refused has to leave the pin showing — otherwise the
    page advertises a release that did not happen, and the user walks away
    believing the next rescan will refill a field it will still skip.

    The "absent is not null" case is the other half: a response that says
    nothing about a field must not be read as saying it is empty.
    """
    _assert_ran(
        js_run,
        [
            "a field that arrived with a value is pinned",
            "a field that arrived empty is not",
            "clearing a field the store accepts releases its pin",
            "and leaves the other fields on that row pinned",
            "storing a value pins the field again",
            "a clear the store rejected leaves the pin exactly where it was",
            "a field the response does not carry keeps its pin: absent is not null",
            "choosing — releases the picker's pin once the store confirms it",
            "a stored hero level is pinned, an unread one is not",
            "blanking it sends the null that releases the lock",
            "and the pin follows the store, not the box",
            "a column the store does not lock never grows a pin",
        ],
    )
    assert js_run["data"]["lock_after_clear"] == "undefined"
    assert js_run["data"]["lock_after_rejected_clear"] == "1"
    # `PATCH /api/heroes/{name}` has no clear_* flag; an explicit null is how
    # `update_hero_stars` is told to store None, which is what releases it.
    assert json.loads(js_run["data"]["hero_level_release_body"]) == {
        "level": None,
        "stars": 2,
        "pellets": 0,
    }


def test_a_piece_cannot_be_deleted_by_one_tap(js_run: dict) -> None:
    """`DELETE /api/gear/{piece_id}` is irreversible: the piece leaves
    gear.json and both SQLite tables, and only a rescan of an inventory that
    still contains it brings it back.

    So the row's button is inert — it arms a dialog that names the piece, and
    nothing but that dialog's own button ever issues the request. Every exit
    (Cancel, backdrop, Escape) disarms as well as closes, so a stray tap on a
    confirm button whose dialog is long gone deletes nothing; the confirm is
    disabled while the request is open, so an impatient double-tap sends one
    DELETE. `remove_calls_before_confirm` is spelled out because every check
    above it is a negative, and a wiring bug that never armed anything would
    satisfy all of them at once.
    """
    _assert_ran(
        js_run,
        [
            "tapping the row's button sends nothing at all",
            "it opens the confirmation instead",
            "which names the piece it is about to destroy",
            "and the row is still on the table",
            "Cancel closes it",
            "and disarms it: a confirm tap after cancelling deletes nothing",
            "another row arms it again",
            "Escape closes it too",
            "and disarms it as well",
            "and a third row arms it again",
            "a click that bubbled out of the panel does not dismiss it",
            "a click on the backdrop itself does",
            "disarmed by that too",
            "confirming DELETEs the row's own API URL",
            "an impatient double-tap sends one DELETE, not two",
            "the dialog closes on success",
            "the row leaves the table",
            (
                "and its trust flag leaves sessionStorage with it, rather than "
                "pinning the banner open over a row nobody can see"
            ),
            "the deletion is confirmed by name",
            "and the row count now describes a two-row table",
            "a refused delete keeps the row",
            "says why",
            (
                "and leaves the dialog open and re-armed rather than dropping "
                "the user back on an unchanged table"
            ),
            "one row matches the active filter",
            (
                "deleting the last row a filter matched leaves the empty "
                "state, not a blank table"
            ),
            "a page with no delete dialog still wires the rest of its table",
        ],
    )
    assert js_run["data"]["remove_calls_before_confirm"] == 0


def test_one_script_serves_both_inventory_pages(js_run: dict) -> None:
    """The heroes table runs the same source with different data attributes —
    which is what makes deleting the two inline copies safe."""
    _assert_ran(
        js_run,
        [
            "a hero row patches its own name-keyed URL",
            "sending the row's whole editable state",
            "a hero name is URL-encoded into the patch path",
            "and writes its payload under the heroes key, never gear's",
            "level sorts as a number, not as text",
        ],
    )
