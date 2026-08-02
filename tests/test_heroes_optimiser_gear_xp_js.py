"""Run the Gear XP planner's real JavaScript and assert on what it does.

Everything on `/optimiser/gear-xp` below the server-rendered form is decided
in the browser: which counts are safe to send, whether to send at all, the
baseline→best delta line, the ordered spend rows, the leftovers, and every
error path. A page-render test can only see the empty form, and a source grep
cannot tell whether any of it works.

So this drives the files for real, the same way
`tests/test_heroes_optimiser_events_js.py` drives the lineup board:
`tests/js/optimiser_gear_xp_harness.js` stands up a fake DOM and a recordable
`fetch`, the two static files are injected into it verbatim, and the whole
thing runs under whichever JS engine the host happens to have. There is no JS
toolchain in this repo and none is added: if no engine is found the module
skips with a reason.

`app.js` is injected alongside the planner because `_layout.html` loads it
first and the planner calls its `window.showToast`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "ks" / "heroes" / "ui" / "static"
HARNESS = Path(__file__).resolve().parent / "js" / "optimiser_gear_xp_harness.js"

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
        ("// @@OPTIMISER_GEAR_XP_JS@@", "optimiser_gear_xp.js"),
    )
    for marker, name in injections:
        assert marker in harness, f"harness lost its {name} injection point"
        source = (STATIC_DIR / name).read_text(encoding="utf-8")
        harness = harness.replace(marker, source)
    script = tmp_path / "optimiser_gear_xp_harness.run.js"
    script.write_text(harness, encoding="utf-8")
    return script


@pytest.fixture(scope="module")
def js_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    engine = _find_engine()
    if engine is None:
        pytest.skip(
            "no JavaScript engine on this host — install node (or bun/deno/"
            "qjs), or run on macOS where JavaScriptCore's jsc ships at "
            f"{_JSC_MACOS}. The planner's JS is only covered where one exists."
        )
    script = _build_script(tmp_path_factory.mktemp("jsgearxp"))
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


# --- wiring ------------------------------------------------------------------


def test_planner_script_is_served_and_is_the_file_on_disk(tmp_path: Path) -> None:
    """Same wiring check the board and the inventory table get: the page's
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

    page = client.get("/optimiser/gear-xp").text
    assert 'src="/static/optimiser_gear_xp.js"' in page
    # app.js comes from _layout.html and has to load first: the planner calls
    # window.showToast off it when a search fails.
    assert page.index('src="/static/app.js"') < page.index(
        'src="/static/optimiser_gear_xp.js"'
    )

    res = client.get("/static/optimiser_gear_xp.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]
    assert res.text == (STATIC_DIR / "optimiser_gear_xp.js").read_text(encoding="utf-8")


def test_the_planner_declares_no_third_showtoast_or_escaper(tmp_path: Path) -> None:
    """Task 5 deleted two local copies of `showToast` and Task 6 two
    *divergent* copies of `esc`. This page adds neither: it raises the shared
    toast, and it needs no escaper at all because it assembles no markup —
    see the next test."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    client = TestClient(create_app(gear_dir=None, heroes_dir=tmp_path))
    planner = client.get("/static/optimiser_gear_xp.js").text

    assert "function esc(" not in planner
    assert "function showToast" not in planner
    assert "window.showToast" in planner


def test_the_planner_builds_every_node_it_shows_rather_than_writing_markup(
    tmp_path: Path,
) -> None:
    """The reason this page carries no escaper: piece names come out of OCR
    and reach the DOM only through `textContent` on nodes built here. An
    `innerHTML` assignment anywhere would reintroduce the injection surface
    and silently need one — so there are none, and the harness's
    "assigns innerHTML nowhere" check proves the *rendered* half of the same
    claim at runtime."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    client = TestClient(create_app(gear_dir=None, heroes_dir=tmp_path))
    planner = client.get("/static/optimiser_gear_xp.js").text
    # Matched with the leading dot so the file's own header comment — which
    # says in words that it assigns no innerHTML — does not satisfy its own
    # prohibition. Any real use is a property access and carries one.
    assert not re.search(r"\.\s*(inner|outer)HTML", planner)
    assert "insertAdjacentHTML" not in planner


def test_every_element_the_planner_looks_up_exists_in_the_page(
    tmp_path: Path,
) -> None:
    """The markup/script contract, derived rather than transcribed: every
    `getElementById("x")` in the served module must have a matching `id="x"`
    in the served page, and every attribute selector must match something.

    This is the one check that spans the two files. The JS harness supplies
    its own DOM, so it cannot notice a template rename; the page tests do not
    read the script. A rename on either side lands here instead of silently
    rendering a dead form in the browser.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.ui.app import create_app

    client = TestClient(create_app(gear_dir=None, heroes_dir=tmp_path))
    body = client.get("/optimiser/gear-xp").text
    script = client.get("/static/optimiser_gear_xp.js").text

    looked_up = set(re.findall(r'getElementById\("([^"]+)"\)', script))
    assert len(looked_up) >= 8, looked_up
    assert not sorted(i for i in looked_up if f'id="{i}"' not in body)

    selectors = set(re.findall(r'querySelectorAll\("\[([a-z0-9-]+)\]"\)', script))
    assert selectors == {
        "data-event",
        "data-fodder",
        "data-mode-for",
        "data-mode-select",
    }, selectors
    assert not sorted(a for a in selectors if f"{a}=" not in body)


# --- behaviour ---------------------------------------------------------------


def test_planner_js_runs_under_a_real_engine(js_run: dict) -> None:
    """Sanity floor: the source parsed and every suite reached its end."""
    assert len(js_run["checks"]) >= 60, len(js_run["checks"])
    assert not _failures(js_run, ["harness ran to completion"])


def test_planner_js_every_behavioural_check(js_run: dict) -> None:
    """Every check in the harness, reported together. Each check's name reads
    as the sentence it is asserting; `tests/js/optimiser_gear_xp_harness.js`
    holds the scenario each belongs to."""
    assert not _failures(js_run), "\n".join(_failures(js_run))
