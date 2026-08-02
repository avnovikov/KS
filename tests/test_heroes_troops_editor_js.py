"""Run the troops editor's real JavaScript and assert on what it does.

`ks/heroes/ui/static/troops.js` carries the whole client-side save state
machine — debounce, dedupe, in-flight coalescing, validation, blank/blur
handling — and `app.js` carries the shared live-region toast. Source-substring
greps cannot tell whether any of that *works*; a page-render test cannot
either, because nothing in the Python suite executes JS.

So this drives the files for real: `tests/js/troops_editor_harness.js` stands
up a fake DOM, a controllable clock and a recordable `fetch`, the two static
files are injected into it verbatim, and the whole thing runs under whichever
JS engine the host happens to have. There is no JS toolchain in this repo and
none is added: if no engine is found the module skips with a reason, so this
is extra coverage where it is available rather than a new hard dependency.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "ks" / "heroes" / "ui" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "troops_editor_harness.js"

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
    injections = (("// @@TROOPS_JS@@", "troops.js"), ("// @@APP_JS@@", "app.js"))
    for marker, name in injections:
        assert marker in harness, f"harness lost its {name} injection point"
        source = (STATIC_DIR / name).read_text(encoding="utf-8")
        harness = harness.replace(marker, source)
    script = tmp_path / "troops_editor_harness.run.js"
    script.write_text(harness, encoding="utf-8")
    return script


@pytest.fixture(scope="module")
def js_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    engine = _find_engine()
    if engine is None:
        pytest.skip(
            "no JavaScript engine on this host — install node (or bun/deno/"
            "qjs), or run on macOS where JavaScriptCore's jsc ships at "
            f"{_JSC_MACOS}. The editor's JS is only covered where one exists."
        )
    script = _build_script(tmp_path_factory.mktemp("jsharness"))
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


def test_troops_editor_js_runs_under_a_real_engine(js_run: dict) -> None:
    """Sanity floor: the source parsed and every suite reached its end."""
    assert len(js_run["checks"]) >= 40, len(js_run["checks"])
    assert not _failures(js_run, ["harness ran to completion"])


def test_the_debounce_is_actually_600ms(js_run: dict) -> None:
    """The harness's fake clock discarded `setTimeout`'s delay, so the
    interval this editor debounces on was asserted by nothing: `DEBOUNCE_MS`
    could be dropped to 1 (a PUT per keystroke) or raised to 60 seconds and
    every check stayed green. The clock records the delay now — the same fix
    tests/js/inventory_harness.js already carried — and this pins the number
    on both sides, in JS and here.
    """
    _assert_ran(js_run, ["and schedules it at the 600ms the brief specifies"])
    assert js_run["data"]["debounce_delays"] == "600"


def test_troops_editor_js_save_state_machine(js_run: dict) -> None:
    """Every behavioural check in the harness, reported together."""
    failures = _failures(js_run)
    assert not failures, "\n".join(
        [f"{len(failures)}/{len(js_run['checks'])} JS checks failed:", *failures]
    )


def test_reverting_an_edit_during_an_in_flight_put_is_not_dropped(
    js_run: dict,
) -> None:
    """Regression: save() must test `saving` *before* deduping.

    `lastSavedBody` is only refreshed on success, so mid-flight it still
    describes the pre-save document. Deduping first meant that typing a value,
    blurring, then typing the *previous* value back and blurring again while
    the first PUT was still open returned early without queueing — the first
    PUT then landed and set `lastSavedBody` to the value the user had just
    undone. The form showed one number, the server held another, and the
    status line said "Saved".
    """
    _assert_ran(
        js_run,
        [
            "an edit starts a PUT",
            "which is still in flight",
            "the revert is held, not sent, while a PUT is in flight",
            "the revert is not dropped: it goes out once the first PUT lands",
            "the last thing the server was told is the value on screen",
            'the status line only says "Saved" once they agree',
        ],
    )
    data = js_run["data"]
    # Spelled out so this test cannot pass by never entering the in-flight
    # path at all, which is exactly how the original harness missed the bug.
    assert data["race_puts_after_edit"] == 1
    assert data["race_puts_during_flight"] == 1, "the second save was not held"
    assert data["race_puts_after_release"] == 2, "the queued save never ran"
    assert data["race_displayed"] == data["race_server"], (
        f"form shows {data['race_displayed']}, server holds {data['race_server']}"
    )
    assert data["race_final_status"] == "Saved"


def test_edits_during_one_in_flight_save_coalesce(js_run: dict) -> None:
    _assert_ran(
        js_run,
        [
            "the first edit is in flight",
            "further edits queue behind it rather than racing it",
            "they coalesce into exactly one more PUT",
            "carrying the final value, not an intermediate one",
            "and the queue drains rather than looping",
            "a queued no-op is deduped once lastSavedBody is fresh",
        ],
    )


def test_out_of_range_value_on_disk_does_not_brick_the_editor(js_run: dict) -> None:
    """`min`/`max` are client-only, so the API can hand back a value the
    editor considers unsendable — `truegold: 7`, or an `infantry: {1: -3}`
    that troops_form.py renders straight through. `readInt()` returns null for
    it and `save()` blocks on *any* null, so one bad number made the whole
    form unsaveable. Repairable values are clamped in the DOM; the rest are
    flagged and named."""
    _assert_ran(
        js_run,
        [
            "a value over max is pulled back to the bound",
            "a value below min is pulled up to the bound",
            "every other field is saveable again",
            "and that first edit carries the corrected value to disk",
            "an unrelated field saves despite the negative on disk",
            "and the repaired negative goes with it",
            "an unclampable value is left alone",
            "it is flagged on load rather than on a save the user cannot trigger",
            "and the banner explains that nothing can save until it is fixed",
            "no field is left flagged invalid",
            "an in-range document is not touched on load",
            "and its banner stays hidden",
        ],
    )


def test_rendering_the_page_never_writes_to_the_troops_file(js_run: dict) -> None:
    """Regression: clamping on load must not PUT.

    An earlier fix clamped *and* saved, so merely opening /inventory/troops
    rewrote troops.yaml and destroyed the pre-clamp value on disk, announced
    only by a self-dismissing toast. Since `max` lives solely in the
    template's attribute, a bound that lagged behind config/troop_stats.yaml
    would have silently downgraded the user's truegold on a page view. The
    clamp now only touches the DOM; the correction reaches disk with the
    user's first real edit, which is what the two follow-up checks assert.
    """
    _assert_ran(
        js_run,
        [
            "a clamping page load fires no PUT at all",
            "clamping a negative fires no PUT either",
            "and fires no PUT",
            "still no PUT",
            "and that first edit carries the corrected value to disk",
            "and the repaired negative goes with it",
        ],
    )
    assert js_run["data"]["clamp_load_puts"] == 0


def test_load_time_repairs_are_reported_where_they_survive(js_run: dict) -> None:
    """Regression: the clamp notice used to be a toast.

    `#toast` is shared and runs on one timer, so a file holding both a
    clampable and an unclampable value produced two messages through the same
    element — the clamp notice overwritten by the validation error a moment
    later, leaving the user with a form showing 5, a disk holding 7, and
    nothing on screen saying so. It is a persistent banner now.
    """
    _assert_ran(
        js_run,
        [
            "the clamp is reported in the persistent banner",
            "and not in a toast the next message would overwrite",
            "the banner says the correction is not on disk yet",
            "the negative is named in the banner",
            "a clamp and an unrepairable value are both reported, not one over the other",
            "the surviving validation error still blocks the save, as it must",
            "and the banner is still on screen next to that toast",
        ],
    )
    notice = js_run["data"]["both_notice"]
    assert "Truegold was 7, shown as 5" in notice
    assert "archers T2" in notice


def test_live_totals_are_grouped_exactly_as_the_server_rendered_them(
    js_run: dict,
) -> None:
    """Jinja formats totals with `"{:,}".format`; the live update must match
    it byte for byte, or the separators change style as soon as the user types
    on a non-en browser."""
    _assert_ran(
        js_run,
        ["live totals pin their grouping instead of following the viewer's locale"],
    )
    if not js_run["data"]["intl_grouping"]:
        # qjs and d8 are routinely built without Intl, and node can be built
        # --without-intl; there toLocaleString("en-US") returns bare digits
        # however correct the source is. The check above still ran and still
        # proves an explicit locale is passed; only this comparison is moot.
        pytest.skip(
            f"{js_run['engine'][0]} has no Intl grouping "
            f"(Intl present: {js_run['data']['intl_present']}), so "
            "toLocaleString cannot produce separators on this host"
        )
    # 1015 + 30084 + 2759 seeded, with tier 2 typed up to 1234567.
    expected = "{:,}".format(1015 + 30084 + 2759 + 1234567)
    assert js_run["data"]["live_total_infantry"] == expected


def test_shared_toast_unhides_the_live_region_before_writing_the_message(
    js_run: dict,
) -> None:
    """Screen readers routinely miss mutations to a hidden live region, so
    app.js must set `hidden = false` before `textContent = String(message)`.
    Asserted by recording the order of the writes app.js actually makes."""
    _assert_ran(
        js_run,
        [
            "app.js publishes window.showToast",
            "the live region is un-hidden",
            "the message is written only after it is visible",
            "the ok style is applied",
            "non-string messages are stringified",
            "the error style is applied",
            "the ordering holds on the error path too",
            "the toast hides and clears itself afterwards",
        ],
    )
    log = js_run["data"]["toast_log"]
    assert log.index("hidden=false") < log.index("text=Saved"), log


def test_heroes_trust_helper_persists_and_scopes_by_inventory_kind(
    js_run: dict,
) -> None:
    """app.js's HeroesTrust is the sessionStorage contract Task 5 consumes
    to survive the page reload a successful rescan triggers. This runs the
    real save()/load()/clear() against a fake sessionStorage rather than
    just reading the source, so a typo'd key or a shape drift would fail
    here instead of silently breaking Task 5's page."""
    _assert_ran(
        js_run,
        [
            "app.js publishes window.HeroesTrust",
            "load() with nothing stored returns null",
            "save() writes to the documented sessionStorage key",
            "the stored shape carries flags/new/changed/incomplete verbatim",
            "save() adds a storedAt timestamp not present in the API payload",
            "load() reads back exactly what save() wrote",
            "gear and heroes payloads live in separate keys",
            "saving heroes does not clobber the gear payload",
            "clear() removes only the requested kind",
            "save() rejects an unknown kind instead of silently writing garbage",
            "load() rejects an unknown kind the same way save() does",
            "clear() rejects an unknown kind the same way save() does",
            "load() returns null instead of throwing on corrupt stored JSON",
            "save() swallows a real sessionStorage failure instead of throwing",
        ],
    )
