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
    """`max` is client-only, so the API can hand back a value the editor
    considers unsendable. It must be clamped, announced and written back —
    not left to make readInt() return null and block every other field."""
    _assert_ran(
        js_run,
        [
            "the out-of-range field is pulled back to its bound",
            "the clamp is announced rather than silent",
            "and written back, so what is stored is what is shown",
            "every other field is saveable again",
            "no field is left flagged invalid",
            "an in-range document is not touched on load",
        ],
    )


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
