# Alliance Member OCR Bake-off Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline alliance-member OCR bake-off that mines unstable name/power cases, scores engines×preprocess settings against a small gold set, and ranks configs vs EasyOCR — without changing live `scan_70`.

**Architecture:** New package under `tools/alliance_ocr_bench/` with shared pairing/stability helpers (copied from the alliance scan so tests do not depend on gitignored `artifacts/`), engine adapters, preprocess profiles, mining CLI, and a bench runner that writes `report.json` + `summary.md`. Heavy OCR libs are optional extras; missing engines are skipped, not fatal.

**Tech Stack:** Python ≥3.12, OpenCV, NumPy, pytest; EasyOCR + pytesseract baseline; optional PaddleOCR, RapidOCR, docTR or Surya.

**Spec:** `docs/superpowers/specs/2026-08-20-alliance-member-ocr-bakeoff-design.md`

## Global Constraints

- Phase 1 is offline only — do not modify `artifacts/alliance-r4-r3-scan/scan_70.py` live OCR path.
- Reuse existing stability semantics: `ocr_edit_distance`, `OCR_MERGE_POWER_GAP=0.5`, `LEVENSHTEIN_MAX_POWER_GAP=5.0`, short/long edit limits from `export_xlsx.py`.
- Reuse production pairing semantics: `parse_power` / `is_name` / `pair_members` from `scan_70.py`.
- Primary ranking metric: row F1 under name-near + power±1.0.
- Engines that fail to import are marked `skipped` in the report.
- Work in a git worktree under `.worktrees/` (repo rule); branch `feature/alliance-member-ocr-bakeoff`.
- Commit frequently after each green task.

## File structure

| Path | Responsibility |
|------|----------------|
| `tools/alliance_ocr_bench/__init__.py` | Package marker |
| `tools/alliance_ocr_bench/schema.py` | `GoldRow`, `OcrHit`, `BenchResult` dataclasses + JSON load/validate |
| `tools/alliance_ocr_bench/stability.py` | `normalize_name`, `ocr_edit_distance`, merge/gap constants |
| `tools/alliance_ocr_bench/pairing.py` | `parse_power`, `is_name`, `pair_members` |
| `tools/alliance_ocr_bench/preprocess.py` | Named preprocess profiles → BGR ndarray |
| `tools/alliance_ocr_bench/mine_unstable.py` | Diff two `names-*.json` → candidates CSV |
| `tools/alliance_ocr_bench/score.py` | Match predictions to gold; compute metrics |
| `tools/alliance_ocr_bench/engines/base.py` | `OcrEngine` protocol + registry |
| `tools/alliance_ocr_bench/engines/easyocr_engine.py` | Baseline adapter |
| `tools/alliance_ocr_bench/engines/tesseract_engine.py` | pytesseract adapter |
| `tools/alliance_ocr_bench/engines/paddle_engine.py` | Optional PaddleOCR |
| `tools/alliance_ocr_bench/engines/rapid_engine.py` | Optional RapidOCR |
| `tools/alliance_ocr_bench/engines/modern_engine.py` | Optional docTR or Surya (whichever installs) |
| `tools/alliance_ocr_bench/run_bench.py` | CLI: gold × engines × profiles → report |
| `tools/alliance_ocr_bench/README.md` | How to mine, confirm gold, run bench |
| `tests/test_alliance_ocr_bench_stability.py` | Edit-distance / normalize |
| `tests/test_alliance_ocr_bench_pairing.py` | Power parse + pairing |
| `tests/test_alliance_ocr_bench_schema.py` | Gold validation |
| `tests/test_alliance_ocr_bench_preprocess.py` | Profile ids + shapes |
| `tests/test_alliance_ocr_bench_mine.py` | Unstable mining on fixtures |
| `tests/test_alliance_ocr_bench_score.py` | Metrics |
| `tests/fixtures/alliance_ocr_bench/` | Tiny JSON + synthetic PNG fixtures |
| `pyproject.toml` | Optional extra `alliance-ocr-bench` |

---

### Task 1: Stability helpers (port from export_xlsx)

**Files:**
- Create: `tools/alliance_ocr_bench/__init__.py`
- Create: `tools/alliance_ocr_bench/stability.py`
- Create: `tests/test_alliance_ocr_bench_stability.py`

**Interfaces:**
- Produces: `normalize_name(name: str) -> str`, `ocr_edit_distance(left: str, right: str) -> int | None`, constants `OCR_MERGE_POWER_GAP`, `LEVENSHTEIN_MAX_POWER_GAP`, `SHORT_NAME_EDIT_LIMIT`, `LONG_NAME_EDIT_LIMIT`, `LONG_NAME_MIN_LEN`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_alliance_ocr_bench_stability.py
from tools.alliance_ocr_bench.stability import (
    LONG_NAME_EDIT_LIMIT,
    OCR_MERGE_POWER_GAP,
    normalize_name,
    ocr_edit_distance,
)


def test_normalize_strips_punctuation_and_case():
    assert normalize_name("  Lord_X! ") == "lordx"


def test_ocr_edit_distance_detects_near_miss():
    assert ocr_edit_distance("DarkLord99", "DarkLord9") == 1


def test_ocr_edit_distance_rejects_unrelated():
    assert ocr_edit_distance("Alice", "Bob") is None


def test_merge_gap_constant():
    assert OCR_MERGE_POWER_GAP == 0.5
    assert LONG_NAME_EDIT_LIMIT == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alliance_ocr_bench_stability.py -v`  
Expected: FAIL (import / module missing)

- [ ] **Step 3: Implement stability.py**

Port logic from `artifacts/alliance-r4-r3-scan/export_xlsx.py` (`normalize_name`, `levenshtein`, `ocr_edit_distance`, constants). Keep behavior identical.

```python
# tools/alliance_ocr_bench/stability.py
from __future__ import annotations

import re

OCR_MERGE_POWER_GAP = 0.5
LEVENSHTEIN_MAX_POWER_GAP = 5.0
SHORT_NAME_EDIT_LIMIT = 1
LONG_NAME_EDIT_LIMIT = 2
LONG_NAME_MIN_LEN = 8


def normalize_name(name: str) -> str:
    cleaned = name.lower().strip()
    return re.sub(r"[^a-z0-9\u00c0-\u024f]+", "", cleaned)


def levenshtein(left: str, right: str) -> int:
    # identical to export_xlsx.levenshtein
    ...


def ocr_edit_distance(left: str, right: str) -> int | None:
    # identical to export_xlsx.ocr_edit_distance
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_stability.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/__init__.py tools/alliance_ocr_bench/stability.py tests/test_alliance_ocr_bench_stability.py
git commit -m "$(cat <<'EOF'
feat(ocr-bench): add alliance OCR stability helpers

EOF
)"
```

---

### Task 2: Pairing helpers (port from scan_70)

**Files:**
- Create: `tools/alliance_ocr_bench/pairing.py`
- Create: `tests/test_alliance_ocr_bench_pairing.py`

**Interfaces:**
- Consumes: none from Task 1 (pairing is independent)
- Produces: `parse_power(text: str) -> float | None`, `is_name(text: str) -> bool`, `pair_members(hits, max_dx=240, min_dy=8, max_dy=100) -> list[dict]` where hits are `(cx, cy, text, conf)` and members are `{"name": str, "power": float}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_alliance_ocr_bench_pairing.py
from tools.alliance_ocr_bench.pairing import is_name, pair_members, parse_power


def test_parse_power_millions():
    assert parse_power("12.5M") == 12.5
    assert parse_power("12.5 M") == 12.5


def test_parse_power_rejects_garbage():
    assert parse_power("hello") is None


def test_is_name_rejects_ranks_and_power():
    assert is_name("DarkLord") is True
    assert is_name("R4") is False
    assert is_name("12.5M") is False


def test_pair_members_links_name_above_power():
    hits = [
        (100.0, 50.0, "DarkLord", 0.9),
        (100.0, 90.0, "12.5M", 0.95),
    ]
    assert pair_members(hits) == [{"name": "DarkLord", "power": 12.5}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alliance_ocr_bench_pairing.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement pairing.py**

Port `POWER_RE`, `SKIP_NAMES`, `parse_power`, `is_name`, `pair_members` from `artifacts/alliance-r4-r3-scan/scan_70.py` (same defaults for `max_dx` / `min_dy` / `max_dy`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_pairing.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/pairing.py tests/test_alliance_ocr_bench_pairing.py
git commit -m "$(cat <<'EOF'
feat(ocr-bench): port member pairing and power parse

EOF
)"
```

---

### Task 3: Gold schema

**Files:**
- Create: `tools/alliance_ocr_bench/schema.py`
- Create: `tests/test_alliance_ocr_bench_schema.py`
- Create: `tests/fixtures/alliance_ocr_bench/gold_sample.json`

**Interfaces:**
- Produces: `@dataclass GoldRow` with fields `id: str`, `shot: str`, `roi: tuple[int,int,int,int] | None`, `name: str`, `power: float`, `tag: str = ""`, `rank_hint: str = ""`; `load_gold(path: Path) -> list[GoldRow]` that raises `ValueError` on bad rows; `@dataclass OcrHit` with `text: str`, `conf: float`, `box_xyxy: tuple[float,float,float,float]`

- [ ] **Step 1: Write fixture + failing tests**

```json
[
  {
    "id": "ex1",
    "shot": "synthetic.png",
    "roi": [10, 20, 200, 80],
    "name": "DarkLord",
    "power": 12.5,
    "tag": "ABC",
    "rank_hint": "r4"
  }
]
```

```python
from pathlib import Path
import pytest
from tools.alliance_ocr_bench.schema import load_gold


FIXTURE = Path("tests/fixtures/alliance_ocr_bench/gold_sample.json")


def test_load_gold_ok():
    rows = load_gold(FIXTURE)
    assert len(rows) == 1
    assert rows[0].name == "DarkLord"
    assert rows[0].power == 12.5
    assert rows[0].roi == (10, 20, 200, 80)


def test_load_gold_rejects_missing_name(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('[{"id":"x","shot":"a.png","power":1.0}]', encoding="utf-8")
    with pytest.raises(ValueError, match="name"):
        load_gold(bad)


def test_load_gold_rejects_nonpositive_power(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '[{"id":"x","shot":"a.png","name":"A","power":0}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="power"):
        load_gold(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alliance_ocr_bench_schema.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement schema.py**

Validate required keys (`id`, `shot`, `name`, `power`), `power > 0`, optional `roi` length 4 ints, optional `tag` / `rank_hint`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_schema.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/schema.py tests/test_alliance_ocr_bench_schema.py tests/fixtures/alliance_ocr_bench/gold_sample.json
git commit -m "$(cat <<'EOF'
feat(ocr-bench): add gold schema loader and validation

EOF
)"
```

---

### Task 4: Mine unstable candidates

**Files:**
- Create: `tools/alliance_ocr_bench/mine_unstable.py`
- Create: `tests/test_alliance_ocr_bench_mine.py`
- Create: `tests/fixtures/alliance_ocr_bench/names_a.json`
- Create: `tests/fixtures/alliance_ocr_bench/names_b.json`

**Interfaces:**
- Consumes: `ocr_edit_distance`, `LEVENSHTEIN_MAX_POWER_GAP`, `normalize_name` from `stability.py`
- Produces: `mine_unstable(old: dict, new: dict) -> list[dict]` with keys `tag`, `old_name`, `new_name`, `old_power`, `new_power`, `edit_distance`, `match_kind` (`LEVENSHTEIN` only for mined rows); `write_candidates_csv(rows, path)`; CLI `python -m tools.alliance_ocr_bench.mine_unstable --old PATH --new PATH --out candidates.csv`

Fixture listings should mirror scan JSON shape:

```json
{
  "alliances": [
    {
      "tag": "ABC",
      "power_rank": 1,
      "r4": [{"name": "DarkLord99", "power": 12.5}],
      "r3": [],
      "r2": [],
      "r5": []
    }
  ]
}
```

In `names_b.json` use `"DarkLord9"` with power `12.5` so mining yields one `LEVENSHTEIN` candidate.

- [ ] **Step 1: Write failing tests**

```python
import json
from pathlib import Path
from tools.alliance_ocr_bench.mine_unstable import mine_unstable, write_candidates_csv

FIX = Path("tests/fixtures/alliance_ocr_bench")


def test_mine_finds_levenshtein_pair():
    old = json.loads((FIX / "names_a.json").read_text())
    new = json.loads((FIX / "names_b.json").read_text())
    rows = mine_unstable(old, new)
    assert len(rows) == 1
    assert rows[0]["match_kind"] == "LEVENSHTEIN"
    assert rows[0]["tag"] == "ABC"
    assert rows[0]["edit_distance"] == 1


def test_write_candidates_csv(tmp_path):
    path = tmp_path / "c.csv"
    write_candidates_csv(
        [
            {
                "tag": "ABC",
                "old_name": "DarkLord99",
                "new_name": "DarkLord9",
                "old_power": 12.5,
                "new_power": 12.5,
                "edit_distance": 1,
                "match_kind": "LEVENSHTEIN",
                "suggested_shots": "ABC-r4-00.png",
            }
        ],
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert "DarkLord99" in text
    assert "suggested_shots" in text
```

Implement mining by flattening each alliance’s r5/r4/r3/r2 into player dicts `{name, power, tag}`, then reuse the pairing approach from `export_xlsx.pair_alliance_players` (exact first, then Levenshtein with power gap). Only emit `LEVENSHTEIN` rows. Add `suggested_shots` as comma-joined `{tag}-r4-00.png,{tag}-r3-00.png,{tag}-members.png` (normalized tag upper/as stored).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alliance_ocr_bench_mine.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement mine_unstable.py** (library + `if __name__ == "__main__"` CLI)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_mine.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/mine_unstable.py tests/test_alliance_ocr_bench_mine.py tests/fixtures/alliance_ocr_bench/names_a.json tests/fixtures/alliance_ocr_bench/names_b.json
git commit -m "$(cat <<'EOF'
feat(ocr-bench): mine unstable OCR name pairs from listings

EOF
)"
```

---

### Task 5: Preprocess profiles

**Files:**
- Create: `tools/alliance_ocr_bench/preprocess.py`
- Create: `tests/test_alliance_ocr_bench_preprocess.py`

**Interfaces:**
- Produces: `PROFILES: dict[str, Callable[[np.ndarray], np.ndarray]]` with at least: `raw`, `gray`, `gray_x2`, `gray_x3`, `clahe_x2`, `otsu_x2`, `otsu_x2_inv`; `apply_profile(name: str, bgr: np.ndarray) -> np.ndarray`; `list_profiles() -> list[str]`

- [ ] **Step 1: Write failing tests**

```python
import numpy as np
from tools.alliance_ocr_bench.preprocess import apply_profile, list_profiles


def test_profile_list_includes_baseline_set():
    names = set(list_profiles())
    for required in {"raw", "gray", "gray_x2", "gray_x3", "clahe_x2", "otsu_x2", "otsu_x2_inv"}:
        assert required in names


def test_gray_x2_doubles_spatial_size():
    img = np.zeros((40, 60, 3), dtype=np.uint8)
    out = apply_profile("gray_x2", img)
    assert out.shape[0] == 80
    assert out.shape[1] == 120


def test_unknown_profile_raises():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    try:
        apply_profile("nope", img)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "nope" in str(exc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alliance_ocr_bench_preprocess.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement preprocess.py** using OpenCV (`cvtColor`, `resize` INTER_CUBIC, `createCLAHE`, `threshold` OTSU). Profiles that produce single-channel images must return HxWx3 by stacking gray→BGR so engines can share one input type **or** document that engines accept 2D — prefer always return HxWx3 BGR for consistency.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_preprocess.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/preprocess.py tests/test_alliance_ocr_bench_preprocess.py
git commit -m "$(cat <<'EOF'
feat(ocr-bench): add preprocess profile grid

EOF
)"
```

---

### Task 6: Engine adapters (EasyOCR + Tesseract)

**Files:**
- Create: `tools/alliance_ocr_bench/engines/__init__.py`
- Create: `tools/alliance_ocr_bench/engines/base.py`
- Create: `tools/alliance_ocr_bench/engines/easyocr_engine.py`
- Create: `tools/alliance_ocr_bench/engines/tesseract_engine.py`
- Create: `tests/test_alliance_ocr_bench_engines.py`

**Interfaces:**
- Produces: `class OcrEngine` protocol with `name: str`, `available() -> bool`, `read(image_bgr: np.ndarray) -> list[OcrHit]`; `get_engines() -> list[OcrEngine]` returning constructed adapters; EasyOCR uses `conf` from reader; Tesseract uses `image_to_data` with `--psm 6` default and conf/100 when conf≥0

- [ ] **Step 1: Write failing tests**

```python
from tools.alliance_ocr_bench.engines.base import get_engines
from tools.alliance_ocr_bench.engines.tesseract_engine import TesseractEngine
import numpy as np


def test_registry_includes_easyocr_and_tesseract():
    names = {e.name for e in get_engines()}
    assert "easyocr" in names
    assert "tesseract" in names


def test_tesseract_available_flag_is_bool():
    eng = TesseractEngine()
    assert isinstance(eng.available(), bool)


def test_unavailable_engine_read_returns_empty_or_raises_not_required():
    # If tesseract binary missing, available() is False and read should raise RuntimeError
    eng = TesseractEngine()
    if not eng.available():
        try:
            eng.read(np.zeros((32, 64, 3), dtype=np.uint8))
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
```

Do **not** require EasyOCR model download in unit tests. Only test registry + availability plumbing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alliance_ocr_bench_engines.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement adapters**

`easyocr_engine.py`: lazy-init `easyocr.Reader(["en"], gpu=False, verbose=False)`; on ImportError `available()` False.  
`tesseract_engine.py`: check `pytesseract` + `tesseract` binary (reuse path discovery pattern from `ks/cartograph/viewport.py` if convenient).

Convert each detection to `OcrHit` with full-image `box_xyxy`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_engines.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/engines tests/test_alliance_ocr_bench_engines.py
git commit -m "$(cat <<'EOF'
feat(ocr-bench): add EasyOCR and Tesseract engine adapters

EOF
)"
```

---

### Task 7: Optional engines (PaddleOCR, RapidOCR, modern)

**Files:**
- Create: `tools/alliance_ocr_bench/engines/paddle_engine.py`
- Create: `tools/alliance_ocr_bench/engines/rapid_engine.py`
- Create: `tools/alliance_ocr_bench/engines/modern_engine.py`
- Modify: `tools/alliance_ocr_bench/engines/base.py` (`get_engines` includes them)
- Modify: `tests/test_alliance_ocr_bench_engines.py`
- Modify: `pyproject.toml` — add optional-dependencies

**Interfaces:**
- Produces: engines named `paddle`, `rapid`, `modern` (modern wraps docTR **or** Surya — try docTR first; if import fails try Surya; if both fail `available()` False). Each follows same `OcrEngine` protocol.

- [ ] **Step 1: Extend registry test**

```python
def test_registry_includes_optional_engine_names():
    names = {e.name for e in get_engines()}
    assert {"paddle", "rapid", "modern"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_alliance_ocr_bench_engines.py::test_registry_includes_optional_engine_names -v`  
Expected: FAIL

- [ ] **Step 3: Implement optional adapters + pyproject extra**

```toml
alliance-ocr-bench = [
  "easyocr>=1.7",
  "paddlepaddle>=2.6; platform_system != 'Darwin' or platform_machine != 'arm64'",
  "paddleocr>=2.7",
  "rapidocr-onnxruntime>=1.3",
  "python-doctr>=0.8",
]
```

Note in README that Paddle on Apple Silicon may need alternate install; skipping is OK.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_engines.py -v`  
Expected: PASS (availability may be False)

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/engines pyproject.toml tests/test_alliance_ocr_bench_engines.py
git commit -m "$(cat <<'EOF'
feat(ocr-bench): register optional Paddle Rapid and modern OCR engines

EOF
)"
```

---

### Task 8: Scoring metrics

**Files:**
- Create: `tools/alliance_ocr_bench/score.py`
- Create: `tests/test_alliance_ocr_bench_score.py`

**Interfaces:**
- Consumes: `GoldRow`, `OcrHit`, `pair_members`, `ocr_edit_distance`, `normalize_name`
- Produces: `@dataclass ScoreSummary` with `name_exact`, `name_near`, `power_exact`, `power_within_0_1`, `power_within_1_0`, `row_tp`, `row_fp`, `row_fn`, `precision`, `recall`, `f1`; `score_predictions(gold: list[GoldRow], predicted_members: list[dict]) -> ScoreSummary`; `hits_to_members(hits: list[OcrHit]) -> list[dict]` converting boxes to centers then `pair_members`

Matching rules for a true positive row:
- name: `normalize_name` equal **or** `ocr_edit_distance` not None
- power: `abs(pred - gold) <= 1.0` for row F1 (also track exact and ±0.1 buckets)

Greedy 1:1 match: prefer exact name, then near, then smaller power gap.

- [ ] **Step 1: Write failing tests**

```python
from tools.alliance_ocr_bench.schema import GoldRow
from tools.alliance_ocr_bench.score import score_predictions


def test_score_perfect_match():
    gold = [GoldRow(id="1", shot="a.png", roi=None, name="DarkLord", power=12.5)]
    pred = [{"name": "DarkLord", "power": 12.5}]
    s = score_predictions(gold, pred)
    assert s.row_tp == 1
    assert s.f1 == 1.0
    assert s.name_exact == 1


def test_score_near_name_counts_row_tp():
    gold = [GoldRow(id="1", shot="a.png", roi=None, name="DarkLord99", power=12.5)]
    pred = [{"name": "DarkLord9", "power": 12.4}]
    s = score_predictions(gold, pred)
    assert s.row_tp == 1
    assert s.name_near == 1
    assert s.power_within_1_0 == 1


def test_score_unrelated_is_fp_and_fn():
    gold = [GoldRow(id="1", shot="a.png", roi=None, name="Alice", power=20.0)]
    pred = [{"name": "Bob", "power": 11.0}]
    s = score_predictions(gold, pred)
    assert s.row_tp == 0
    assert s.row_fp == 1
    assert s.row_fn == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alliance_ocr_bench_score.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement score.py**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_score.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/score.py tests/test_alliance_ocr_bench_score.py
git commit -m "$(cat <<'EOF'
feat(ocr-bench): score name and power predictions against gold

EOF
)"
```

---

### Task 9: Bench runner CLI

**Files:**
- Create: `tools/alliance_ocr_bench/run_bench.py`
- Create: `tests/test_alliance_ocr_bench_run.py`
- Create: `tests/fixtures/alliance_ocr_bench/synthetic.png` (generated in test or committed tiny PNG)
- Modify: ensure `tools` is importable — add empty `tools/__init__.py` if needed; pytest `pythonpath = ["."]` already set

**Interfaces:**
- Produces: `run_bench(gold_path, shots_root, out_dir, engines=None, profiles=None) -> Path` writing `report.json` and `summary.md`; CLI flags `--gold`, `--shots-root`, `--out`, `--engines`, `--profiles`
- Default member band when `roi` is null: `(x0=70, y0=250, x1=1030, y1=1600)` (aligned with reocr member crops)
- For each gold row: load shot from `shots_root / shot`, crop ROI or default band, apply profile, run engine, convert hits→members, score **that single gold row** against predictions (micro-average across rows into one ScoreSummary per engine×profile)
- Skipped engine → report entry `{"engine": "...", "status": "skipped", "reason": "..."}`
- Also record `latency_ms_median`

- [ ] **Step 1: Write failing test with fake engine**

Inject via optional parameter `engine_overrides: list[OcrEngine] | None` for tests:

```python
from pathlib import Path
import cv2
import numpy as np
from tools.alliance_ocr_bench.schema import OcrHit
from tools.alliance_ocr_bench.run_bench import run_bench


class FakeEngine:
    name = "fake"

    def available(self) -> bool:
        return True

    def read(self, image_bgr: np.ndarray) -> list[OcrHit]:
        h, w = image_bgr.shape[:2]
        return [
            OcrHit("DarkLord", 0.99, (0, 0, w * 0.5, h * 0.4)),
            OcrHit("12.5M", 0.99, (0, h * 0.5, w * 0.5, h * 0.9)),
        ]


def test_run_bench_writes_report(tmp_path):
    shot = tmp_path / "synthetic.png"
    cv2.imwrite(str(shot), np.zeros((100, 200, 3), dtype=np.uint8))
    gold = tmp_path / "gold.json"
    gold.write_text(
        '[{"id":"1","shot":"synthetic.png","roi":null,"name":"DarkLord","power":12.5}]',
        encoding="utf-8",
    )
    out = tmp_path / "out"
    report_path = run_bench(
        gold_path=gold,
        shots_root=tmp_path,
        out_dir=out,
        engine_overrides=[FakeEngine()],
        profiles=["raw"],
    )
    assert report_path.exists()
    text = (out / "summary.md").read_text(encoding="utf-8")
    assert "fake" in text
    assert "f1" in text.lower() or "F1" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_alliance_ocr_bench_run.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement run_bench.py**

Write `report.json` as list of `{engine, profile, status, metrics: {...}, latency_ms_median}` sorted by F1 desc (skipped last). `summary.md` markdown table of top results + baseline `easyocr`/`raw` or `easyocr`/`gray` callout when present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alliance_ocr_bench_run.py tests/test_alliance_ocr_bench_*.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/alliance_ocr_bench/run_bench.py tools/__init__.py tests/test_alliance_ocr_bench_run.py
git commit -m "$(cat <<'EOF'
feat(ocr-bench): add offline bench runner and report output

EOF
)"
```

---

### Task 10: README + first real mine command

**Files:**
- Create: `tools/alliance_ocr_bench/README.md`
- Modify: `docs/superpowers/specs/2026-08-20-alliance-member-ocr-bakeoff-design.md` — set Status to `Approved` / link the plan

**Interfaces:** none (docs)

- [ ] **Step 1: Write README covering**

1. Install: `pip install -e ".[dev,alliance-ocr-bench]"` (plus system `tesseract`)
2. Mine:

```bash
python -m tools.alliance_ocr_bench.mine_unstable \
  --old artifacts/alliance-r4-r3-scan/names-2026-08-18T0042.json \
  --new artifacts/alliance-r4-r3-scan/names-2026-08-18T2035.json \
  --out artifacts/alliance-ocr-bench/candidates.csv
```

3. Hand-confirm ≥30 rows into `artifacts/alliance-ocr-bench/gold.json` (schema from Task 3)
4. Run bench:

```bash
python -m tools.alliance_ocr_bench.run_bench \
  --gold artifacts/alliance-ocr-bench/gold.json \
  --shots-root artifacts/alliance-r4-r3-scan \
  --out artifacts/alliance-ocr-bench/out
```

5. How to read `summary.md` / promote a winner later (phase 2 — out of scope)

- [ ] **Step 2: Run unit suite once more**

Run: `pytest tests/test_alliance_ocr_bench_*.py -v`  
Expected: PASS

- [ ] **Step 3: Smoke mine against real artifacts if present** (skip if files missing)

Run the mine command above; expect `candidates.csv` with ≥1 row when both JSONs exist.

- [ ] **Step 4: Commit**

```bash
git add tools/alliance_ocr_bench/README.md docs/superpowers/specs/2026-08-20-alliance-member-ocr-bakeoff-design.md docs/superpowers/plans/2026-08-20-alliance-member-ocr-bakeoff.md
git commit -m "$(cat <<'EOF'
docs(ocr-bench): add bake-off README and link plan to spec

EOF
)"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|------------------|------|
| Mine unstable via existing rules | Task 4 |
| Hand-confirm gold | Task 3 schema + Task 10 workflow |
| Engines: EasyOCR, Tesseract, Paddle, Rapid, modern | Tasks 6–7 |
| Settings/preprocess grid | Task 5 |
| Score name+power precision/recall (F1) | Task 8 |
| Report + no live scan change | Task 9–10; Global Constraints |
| Skip unavailable engines | Tasks 6–7, 9 |
| Latency secondary metric | Task 9 |

## Placeholder / consistency self-check

- No TBD steps; docTR-vs-Surya resolved as try-docTR-then-Surya in Task 7.
- Types aligned: `GoldRow`, `OcrHit`, `pair_members` dicts, `ScoreSummary`.
- Default ROI band documented once in Task 9.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-20-alliance-member-ocr-bakeoff.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
