# Kingshot Gather Optimiser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a hybrid CLI that detects a free march, scores gather tiles by `haul / (t_gather + 2×t_march)`, prints a proposal, and taps only after `y` (default `dry_run: true`).

**Architecture:** Pure scoring + policy; ADB device I/O; OpenCV/OCR vision; executor gated by CLI confirm and dry-run. Layers never cross responsibilities from the design spec.

**Tech Stack:** Python 3.12+, pytest, PyYAML, adbutils, OpenCV (`opencv-python-headless`), pytesseract (system Tesseract via Homebrew).

**Spec:** `docs/superpowers/specs/2026-07-21-kingshot-gather-optimiser-design.md`

## Global Constraints

- Python 3.12+ only; local venv at `/Users/alexei/KS/.venv` (do not use LexVox `fnbo_venv`).
- Default `dry_run: true` — never tap unless config flips it **and** user types `y`.
- Fail closed: OCR/vision failure drops the candidate; unknown UI → no taps.
- Resources are `bread` | `wood` | `stone` | `iron` (not food/gold).
- No MAS SDK, no memory reads, no multi-account in v1.
- Tests must not require a live emulator except Task 8 smoke check.
- Commit after each task completes green.

## File structure

| Path | Responsibility |
|------|----------------|
| `pyproject.toml` | Package metadata, deps, pytest config |
| `config/params.yaml` | ADB, dry_run, account rates/load, taps, scoring limits |
| `ks/__init__.py` | Package marker |
| `ks/models.py` | `GatherCandidate`, `ScoredGather`, `Proposal`, `NothingToDo`, actions |
| `ks/config.py` | Load/validate `params.yaml` |
| `ks/policy/scoring.py` | Pure throughput math |
| `ks/policy/gather.py` | Choose best candidate → `Proposal` \| `NothingToDo` |
| `ks/device/adb.py` | Screencap / tap / swipe via adbutils |
| `ks/device/base.py` | `Device` protocol |
| `ks/executor.py` | Run action list with caps + delays; respect dry_run |
| `ks/vision/templates.py` | Template match |
| `ks/vision/ocr.py` | Read amounts and `mm:ss` / `Hh Mm` march times |
| `ks/cli.py` | Entrypoint: run once → print → confirm → execute |
| `assets/templates/` | UI templates (filled after capture) |
| `assets/reference/tile_baselines.yaml` | Optional community tile defaults |
| `tests/` | Unit tests + synthetic image fixtures |
| `scripts/adb_smoke.py` | Print `adb devices` + one screencap path |
| `scripts/capture_templates.md` | Manual capture checklist |

---

### Task 1: Scaffold, config, and params

**Files:**
- Create: `pyproject.toml`
- Create: `ks/__init__.py`
- Create: `ks/config.py`
- Create: `config/params.yaml`
- Create: `tests/test_config.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: `load_config(path: Path | None = None) -> AppConfig` with nested fields matching YAML below

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path

from ks.config import load_config


def test_load_config_defaults_dry_run(tmp_path: Path):
    p = tmp_path / "params.yaml"
    p.write_text(
        """
dry_run: true
adb:
  serial: null
account:
  march_load: 1000000
  gather_rate_per_sec:
    bread: 200.0
    wood: 200.0
    stone: 40.0
    iron: 10.0
scoring:
  candidate_limit: 5
resources:
  preference_order: [bread, wood, stone, iron]
executor:
  max_taps_per_proposal: 20
  tap_delay_ms: 250
  tap_jitter_ms: 50
vision:
  match_threshold: 0.85
navigation: {}
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.dry_run is True
    assert cfg.account.march_load == 1_000_000
    assert cfg.account.gather_rate_per_sec["bread"] == 200.0
    assert cfg.scoring.candidate_limit == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/alexei/KS && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" && pytest tests/test_config.py -v`

Expected: FAIL (package / `load_config` missing) — if pip fails because `pyproject.toml` missing, create it in Step 3 then re-run to see import failure.

- [ ] **Step 3: Write minimal implementation**

Create `.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.DS_Store
*.egg-info/
dist/
build/
artifacts/
```

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ks"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "PyYAML>=6.0",
  "adbutils>=2.8",
  "opencv-python-headless>=4.8",
  "numpy>=1.26",
  "pytesseract>=0.3.10",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
ks = "ks.cli:main"

[tool.setuptools.packages.find]
include = ["ks*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create `ks/__init__.py` (empty).

Create `config/params.yaml` with the same keys as the test (real defaults; keep `dry_run: true`).

Create `ks/config.py` with dataclasses `AccountConfig`, `ScoringConfig`, `ExecutorConfig`, `VisionConfig`, `AppConfig` and `load_config` that reads YAML, raises `ValueError` if any `gather_rate_per_sec` ≤ 0 or `march_load` ≤ 0.

- [ ] **Step 4: Run test to verify it passes**

Run: `source /Users/alexei/KS/.venv/bin/activate && pytest tests/test_config.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .gitignore pyproject.toml ks/__init__.py ks/config.py config/params.yaml tests/test_config.py
git commit -m "chore: scaffold ks package and config loader"
```

---

### Task 2: Domain models and throughput scoring

**Files:**
- Create: `ks/models.py`
- Create: `ks/policy/__init__.py`
- Create: `ks/policy/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: nothing from Task 1 except resource name strings
- Produces:
  - `GatherCandidate(resource: str, tile_amount: float, march_time_one_way_s: float, vision_confidence: float)`
  - `ScoredGather(candidate, haul, t_gather_s, t_march_round_s, score)`
  - `score_gather(candidate: GatherCandidate, *, march_load: float, gather_rate_per_sec: float) -> ScoredGather`
  - `best_gather(scored: list[ScoredGather]) -> ScoredGather | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scoring.py
from ks.models import GatherCandidate
from ks.policy.scoring import best_gather, score_gather


def test_haul_capped_by_march_load():
    c = GatherCandidate("bread", tile_amount=5_000_000, march_time_one_way_s=60.0, vision_confidence=0.9)
    s = score_gather(c, march_load=1_000_000, gather_rate_per_sec=200.0)
    assert s.haul == 1_000_000
    assert s.t_march_round_s == 120.0
    assert s.t_gather_s == 1_000_000 / 200.0
    assert s.score == s.haul / (s.t_gather_s + s.t_march_round_s)


def test_nearer_smaller_tile_can_beat_distant_huge_tile():
    near = GatherCandidate("bread", 200_000, march_time_one_way_s=30.0, vision_confidence=0.9)
    far = GatherCandidate("bread", 14_000_000, march_time_one_way_s=3600.0, vision_confidence=0.9)
    load = 500_000
    rate = 200.0
    sn = score_gather(near, march_load=load, gather_rate_per_sec=rate)
    sf = score_gather(far, march_load=load, gather_rate_per_sec=rate)
    assert sn.score > sf.score
    assert best_gather([sf, sn]) is sn


def test_rejects_non_positive_inputs():
    c = GatherCandidate("wood", 1000, 10.0, 0.9)
    try:
        score_gather(c, march_load=0, gather_rate_per_sec=10.0)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring.py -v`

Expected: FAIL — import errors

- [ ] **Step 3: Write minimal implementation**

`ks/models.py` — dataclasses for `GatherCandidate`, `ScoredGather`, plus stubs for later:

```python
from dataclasses import dataclass
from typing import Literal

Resource = Literal["bread", "wood", "stone", "iron"]

@dataclass(frozen=True)
class GatherCandidate:
    resource: str
    tile_amount: float
    march_time_one_way_s: float
    vision_confidence: float

@dataclass(frozen=True)
class ScoredGather:
    candidate: GatherCandidate
    haul: float
    t_gather_s: float
    t_march_round_s: float
    score: float

@dataclass(frozen=True)
class Tap:
    x: int
    y: int

@dataclass(frozen=True)
class Wait:
    ms: int

Action = Tap | Wait

@dataclass(frozen=True)
class Proposal:
    kind: Literal["gather"]
    scored: ScoredGather
    actions: tuple[Action, ...]
    rationale: str
    debug_frame: str | None = None

@dataclass(frozen=True)
class NothingToDo:
    reason: str
```

`ks/policy/scoring.py`:

```python
from ks.models import GatherCandidate, ScoredGather


def score_gather(
    candidate: GatherCandidate,
    *,
    march_load: float,
    gather_rate_per_sec: float,
) -> ScoredGather:
    if march_load <= 0:
        raise ValueError(f"march_load must be > 0; got {march_load}")
    if gather_rate_per_sec <= 0:
        raise ValueError(f"gather_rate_per_sec must be > 0; got {gather_rate_per_sec}")
    if candidate.tile_amount < 0:
        raise ValueError(f"tile_amount must be >= 0; got {candidate.tile_amount}")
    if candidate.march_time_one_way_s < 0:
        raise ValueError(
            f"march_time_one_way_s must be >= 0; got {candidate.march_time_one_way_s}"
        )
    haul = min(candidate.tile_amount, march_load)
    t_gather_s = haul / gather_rate_per_sec
    t_march_round_s = 2.0 * candidate.march_time_one_way_s
    denom = t_gather_s + t_march_round_s
    if denom <= 0:
        raise ValueError("total time must be > 0")
    return ScoredGather(
        candidate=candidate,
        haul=haul,
        t_gather_s=t_gather_s,
        t_march_round_s=t_march_round_s,
        score=haul / denom,
    )


def best_gather(scored: list[ScoredGather]) -> ScoredGather | None:
    if not scored:
        return None
    return max(scored, key=lambda s: s.score)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ks/models.py ks/policy/__init__.py ks/policy/scoring.py tests/test_scoring.py
git commit -m "feat: add load-capped gather throughput scoring"
```

---

### Task 3: Device protocol and ADB adapter

**Files:**
- Create: `ks/device/__init__.py`
- Create: `ks/device/base.py`
- Create: `ks/device/adb.py`
- Create: `ks/device/fake.py`
- Create: `tests/test_device_fake.py`

**Interfaces:**
- Consumes: optional `serial` from config
- Produces:
  - Protocol `Device`: `screencap() -> bytes` (PNG), `tap(x: int, y: int) -> None`, `swipe(...)` optional
  - `FakeDevice` recording taps for tests
  - `AdbDevice.connect(serial: str | None = None) -> AdbDevice`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_device_fake.py
from ks.device.fake import FakeDevice


def test_fake_device_records_taps_and_returns_png():
    d = FakeDevice(png_bytes=b"\x89PNG\r\n\x1a\nfake")
    assert d.screencap().startswith(b"\x89PNG")
    d.tap(10, 20)
    d.tap(30, 40)
    assert d.taps == [(10, 20), (30, 40)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_device_fake.py -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`ks/device/base.py` — `typing.Protocol` named `Device`.

`ks/device/fake.py` — store `png_bytes`, append taps.

`ks/device/adb.py` — wrap `adbutils.AdbClient().device(serial=...)`; `screencap` via `device.shell("screencap -p", encoding=None)` or `device.screenshot()` depending on adbutils API; `tap` via `input tap x y`. Raise clear `RuntimeError` if no device.

Keep ADB code thin; do not call real devices from unit tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_device_fake.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ks/device/ tests/test_device_fake.py
git commit -m "feat: add Device protocol with Fake and ADB adapters"
```

---

### Task 4: Executor with dry-run and tap cap

**Files:**
- Create: `ks/executor.py`
- Create: `tests/test_executor.py`

**Interfaces:**
- Consumes: `Device`, `Action` (`Tap` | `Wait`), executor config fields
- Produces: `execute(device, actions, *, dry_run: bool, max_taps: int, tap_delay_ms: int, tap_jitter_ms: int) -> ExecuteResult` where `ExecuteResult` has `taps_performed: int`, `skipped_dry_run: bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_executor.py
from ks.device.fake import FakeDevice
from ks.executor import execute
from ks.models import Tap, Wait


def test_dry_run_performs_zero_taps():
    d = FakeDevice(b"png")
    result = execute(
        d,
        (Tap(1, 2), Wait(10), Tap(3, 4)),
        dry_run=True,
        max_taps=20,
        tap_delay_ms=0,
        tap_jitter_ms=0,
    )
    assert result.skipped_dry_run is True
    assert result.taps_performed == 0
    assert d.taps == []


def test_live_respects_max_taps():
    d = FakeDevice(b"png")
    try:
        execute(
            d,
            (Tap(1, 1), Tap(2, 2), Tap(3, 3)),
            dry_run=False,
            max_taps=2,
            tap_delay_ms=0,
            tap_jitter_ms=0,
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "max_taps" in str(e)
    assert len(d.taps) <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_executor.py -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `execute`: if `dry_run`, return immediately without calling `device.tap`. Otherwise count taps; if planned tap count > `max_taps`, raise before any tap. Apply `time.sleep((tap_delay_ms + random(0..jitter))/1000)` between taps when delay > 0. `Wait` only sleeps when not dry_run.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_executor.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ks/executor.py tests/test_executor.py
git commit -m "feat: add gated action executor with dry-run"
```

---

### Task 5: Vision helpers (template match + OCR parsers)

**Files:**
- Create: `ks/vision/__init__.py`
- Create: `ks/vision/templates.py`
- Create: `ks/vision/ocr.py`
- Create: `tests/test_ocr_parse.py`
- Create: `tests/test_templates.py`
- Create: `tests/fixtures/` (generated in test via numpy/cv2 — no binary commit required)

**Interfaces:**
- Consumes: PNG/ndarray screenshots
- Produces:
  - `match_template(haystack_bgr, needle_bgr, threshold: float) -> Match | None` with `x, y, score`
  - `parse_rss_amount(text: str) -> float` (supports `70K`, `1.2M`, `14M`, plain ints)
  - `parse_march_time(text: str) -> float` seconds (supports `1:30`, `01:30:00`, `1h 30m`, `90s`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ocr_parse.py
from ks.vision.ocr import parse_march_time, parse_rss_amount


def test_parse_rss_amount_suffixes():
    assert parse_rss_amount("70K") == 70_000
    assert parse_rss_amount("1.2M") == 1_200_000
    assert parse_rss_amount("14M") == 14_000_000
    assert parse_rss_amount("150000") == 150_000


def test_parse_march_time_formats():
    assert parse_march_time("1:30") == 90.0
    assert parse_march_time("1h 30m") == 5400.0
    assert parse_march_time("90s") == 90.0
```

```python
# tests/test_templates.py
import numpy as np

from ks.vision.templates import match_template


def test_match_template_finds_bright_square():
    hay = np.zeros((200, 200, 3), dtype=np.uint8)
    hay[50:70, 80:100] = 255
    needle = np.full((20, 20, 3), 255, dtype=np.uint8)
    m = match_template(hay, needle, threshold=0.9)
    assert m is not None
    assert abs(m.x - 80) <= 2
    assert abs(m.y - 50) <= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ocr_parse.py tests/test_templates.py -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Implement parsers with explicit `ValueError` on garbage input. Template match uses `cv2.matchTemplate` + `TM_CCOEFF_NORMED`; return center-or-top-left consistently (document: **top-left of match**). Do not require live Tesseract for these unit tests — keep raw `pytesseract` calls behind `ocr_region(image, box) -> str` used later; unit-test only parsers here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ocr_parse.py tests/test_templates.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ks/vision/ tests/test_ocr_parse.py tests/test_templates.py
git commit -m "feat: add template match and OCR amount/time parsers"
```

---

### Task 6: Gather policy (score candidates → Proposal)

**Files:**
- Create: `ks/policy/gather.py`
- Create: `tests/test_gather_policy.py`

**Interfaces:**
- Consumes: `score_gather`, `best_gather`, `AppConfig` account rates, list of `GatherCandidate`, optional `actions` builder
- Produces:
  - `propose_gather(candidates: list[GatherCandidate], cfg: AppConfig, actions: tuple[Action, ...]) -> Proposal | NothingToDo`
  - Formats `rationale` including haul, times, score

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gather_policy.py
from pathlib import Path

from ks.config import load_config
from ks.models import GatherCandidate, NothingToDo, Proposal, Tap
from ks.policy.gather import propose_gather

_MIN_YAML = """
dry_run: true
adb:
  serial: null
account:
  march_load: 500000
  gather_rate_per_sec:
    bread: 200.0
    wood: 200.0
    stone: 40.0
    iron: 10.0
scoring:
  candidate_limit: 5
resources:
  preference_order: [bread, wood, stone, iron]
executor:
  max_taps_per_proposal: 20
  tap_delay_ms: 250
  tap_jitter_ms: 50
vision:
  match_threshold: 0.85
navigation: {}
"""


def _cfg(tmp_path: Path):
    p = tmp_path / "params.yaml"
    p.write_text(_MIN_YAML, encoding="utf-8")
    return load_config(p)


def test_propose_gather_picks_highest_score(tmp_path: Path):
    cfg = _cfg(tmp_path)
    near = GatherCandidate("bread", 200_000, 30.0, 0.9)
    far = GatherCandidate("bread", 14_000_000, 3600.0, 0.9)
    result = propose_gather([far, near], cfg, actions=(Tap(100, 200),))
    assert isinstance(result, Proposal)
    assert result.scored.candidate is near
    assert "score=" in result.rationale


def test_propose_gather_empty_is_nothing(tmp_path: Path):
    cfg = _cfg(tmp_path)
    result = propose_gather([], cfg, actions=())
    assert isinstance(result, NothingToDo)
```

In `propose_gather`: skip candidates whose `resource` is missing from `gather_rate_per_sec`; skip if `vision_confidence` < `cfg.vision.match_threshold`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gather_policy.py -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`propose_gather` filters → scores → `best_gather` → builds `Proposal` or `NothingToDo(reason=...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gather_policy.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ks/policy/gather.py tests/test_gather_policy.py
git commit -m "feat: add gather proposal policy from scored candidates"
```

---

### Task 7: CLI confirm loop

**Files:**
- Create: `ks/cli.py`
- Create: `tests/test_cli_confirm.py`

**Interfaces:**
- Consumes: `Proposal | NothingToDo`, `execute`, stdin
- Produces: `main(argv: list[str] | None = None) -> int`; `confirm_yes_no(prompt: str, input_fn=input) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_confirm.py
from ks.cli import confirm_yes_no


def test_confirm_yes():
    assert confirm_yes_no("Go?", input_fn=lambda _: "y") is True


def test_confirm_no():
    assert confirm_yes_no("Go?", input_fn=lambda _: "n") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_confirm.py -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`confirm_yes_no` accepts only `y`/`n` (case-insensitive); re-prompt on garbage when using real input; for injected `input_fn`, treat unexpected as `False`.

`main`:
1. Load config (`--config` path optional)
2. For v1 unit path: support `--demo-candidates` JSON file OR a `--fixture-proposal` mode used in tests
3. Print `NothingToDo` / `Proposal.rationale`
4. If proposal and user says `y`, call `execute` with config dry_run/max taps
5. Exit codes: `0` ok, `2` nothing to do, `1` error

Also implement a **fixture mode** so CI needs no emulator:

```bash
ks --candidates-json tests/fixtures/candidates.json
```

Where JSON is a list of candidate dicts; CLI scores via `propose_gather` and prints rationale; with `dry_run: true` never taps.

- [ ] **Step 4: Run tests + demo CLI**

Run: `pytest tests/test_cli_confirm.py -v`

Create `tests/fixtures/candidates.json` with two bread candidates (near/far). Run:

```bash
printf 'n\n' | ks --candidates-json tests/fixtures/candidates.json
```

Expected: prints proposal with near tile winning; no taps; exit 0 after `n`.

- [ ] **Step 5: Commit**

```bash
git add ks/cli.py tests/test_cli_confirm.py tests/fixtures/candidates.json
git commit -m "feat: add CLI proposal confirm for gather optimiser"
```

---

### Task 8: Emulator runtime + ADB smoke (manual gate)

**Files:**
- Create: `scripts/adb_smoke.py`
- Create: `scripts/capture_templates.md`
- Create: `assets/templates/.gitkeep`
- Create: `assets/reference/tile_baselines.yaml`

**Interfaces:**
- Consumes: working BlueStacks/Play Games + platform-tools `adb`
- Produces: documented steps; smoke script writes `artifacts/smoke.png`

- [ ] **Step 1: Install runtime on this Mac**

1. Install BlueStacks from official site (Apple Silicon build) **or** Google Play Games if BlueStacks fails.
2. `brew install android-platform-tools tesseract`
3. Enable BlueStacks ADB (settings → advanced → ADB); connect (`adb connect 127.0.0.1:<port>` as shown in BlueStacks).
4. Install Kingshot from Play Store inside the runtime.

- [ ] **Step 2: Write smoke script**

`scripts/adb_smoke.py` uses `AdbDevice`, lists serial, writes screencap to `artifacts/smoke.png`, prints screen size.

- [ ] **Step 3: Run smoke**

Run: `source .venv/bin/activate && python scripts/adb_smoke.py`

Expected: device listed; `artifacts/smoke.png` exists and is a valid screenshot of the emulator.

- [ ] **Step 4: Capture templates (manual)**

Follow `scripts/capture_templates.md`: city with free march UI, map search, tile info with amount + march time, gather confirm button. Save under `assets/templates/` with names referenced in `config/params.yaml` (`vision.templates.*` keys — add these keys when capturing).

Add `assets/reference/tile_baselines.yaml` from kingshot.fun table (levels 1–8 amounts + normal gather minutes) as **defaults only**, not live truth.

- [ ] **Step 5: Commit**

```bash
git add scripts/ assets/config/params.yaml
git commit -m "chore: add ADB smoke script and template capture notes"
```

(Commit only non-secret assets; screenshots of your city are fine locally — avoid committing if they reveal account identity you care about; prefer generic UI crops.)

---

### Task 9: Live gather path wiring (coords + OCR regions from config)

**Files:**
- Modify: `ks/cli.py`
- Modify: `ks/config.py` / `config/params.yaml` (add `navigation` tap points + `ocr_regions`)
- Create: `ks/pipeline/gather_once.py`
- Create: `tests/test_gather_once_offline.py`

**Interfaces:**
- Consumes: `Device`, `AppConfig`, vision helpers, `propose_gather`, `execute`
- Produces: `gather_once(device, cfg, *, input_fn=input) -> int`

**Offline test strategy:** inject a `FakeDevice` plus a monkeypatched `collect_candidates(device, cfg) -> list[GatherCandidate]` returning fixtures — proves orchestration without emulator.

- [ ] **Step 1: Write failing offline orchestration test**

```python
# tests/test_gather_once_offline.py
from ks.device.fake import FakeDevice
from ks.models import GatherCandidate
from ks.pipeline.gather_once import gather_once


def test_gather_once_dry_run_yes_performs_zero_taps(tmp_path, monkeypatch, capsys):
    from tests.test_gather_policy import _cfg

    cfg = _cfg(tmp_path)
    assert cfg.dry_run is True
    device = FakeDevice(b"\x89PNG\r\n\x1a\nfake")

    def fake_collect(device, cfg):
        return [
            GatherCandidate("bread", 14_000_000, 3600.0, 0.9),
            GatherCandidate("bread", 200_000, 30.0, 0.9),
        ]

    monkeypatch.setattr("ks.pipeline.gather_once.collect_candidates", fake_collect)
    monkeypatch.setattr("ks.pipeline.gather_once.detect_free_march", lambda device, cfg: True)

    code = gather_once(device, cfg, input_fn=lambda _: "y")
    captured = capsys.readouterr().out
    assert code == 0
    assert "score=" in captured
    assert device.taps == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gather_once_offline.py -v`

Expected: FAIL

- [ ] **Step 3: Implement `gather_once`**

Flow:
1. Screencap → detect free march via template (if template missing, `--assume-free-march` flag for bring-up)
2. Navigate using `cfg.navigation` taps (open map / search)
3. `collect_candidates`: for up to `candidate_limit` results, OCR amount + march time regions; drop failures
4. `propose_gather` → print → confirm → `execute`
5. Optional verify template for “marching” icon; on miss print `verify failed` but exit 0 if taps were attempted

Keep navigation coordinates **only** in YAML — never hardcode magic numbers in Python.

- [ ] **Step 4: Run unit tests**

Run: `pytest -v`

Expected: all PASS

- [ ] **Step 5: Manual live dry-run**

With emulator up and templates filled:

```bash
ks --live
# dry_run true → should print proposal, on y still no taps
```

Then set `dry_run: false` only when you are ready; confirm `y` once.

- [ ] **Step 6: Commit**

```bash
git add ks/pipeline/ ks/cli.py ks/config.py config/params.yaml tests/test_gather_once_offline.py
git commit -m "feat: wire gather_once pipeline with config-driven navigation"
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Throughput score haul/(gather+round-trip) | Task 2 |
| Load cap | Task 2 |
| Hybrid y/n confirm | Task 7 |
| dry_run default / no silent taps | Tasks 1, 4, 7 |
| Fail closed OCR | Tasks 6, 9 |
| ADB device layer | Tasks 3, 8 |
| Vision templates + OCR | Tasks 5, 9 |
| params.yaml account rates/load | Tasks 1, 6 |
| BlueStacks/Play Games prereq | Task 8 |
| Unit tests without live game | Tasks 2–7, 9 offline |
| One proposal per CLI run | Tasks 7, 9 |

## Placeholder scan

None intentional. Task 8 is inherently manual (install GUI apps); automation stops at ADB smoke.

## Type consistency

- `GatherCandidate` / `ScoredGather` / `Proposal` / `NothingToDo` / `Tap` / `Wait` defined in Task 2 `ks/models.py` and reused thereafter.
- `load_config` → `AppConfig` from Task 1 used by policy/CLI/pipeline.
- `Device` protocol from Task 3 used by executor and pipeline.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-21-kingshot-gather-optimiser.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — run tasks in this session with checkpoints  

Which approach?
