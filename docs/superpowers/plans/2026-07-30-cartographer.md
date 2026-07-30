# Cartographer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline-first cartographer CLI that plans/maps ±R tiles around a viewport center, with BlueStacks ADB ready for live capture when online.

**Architecture:** Pure cartograph library (mask, project, sweep, dedupe, pipeline) + thin device I/O. Fixture/dry-run paths need no emulator; live path reuses `AdbDevice` and a BlueStacks connect helper.

**Tech Stack:** Python 3.12+, pytest, PyYAML, adbutils, OpenCV, pytesseract, existing `ks/device` + `ks/placement/viewport_ocr`.

## Global Constraints

- Radius CLI range 20…50; default 30  
- Fail closed on unreadable center viewport  
- Config in `config/params.yaml` under `cartograph:`  
- Lessons in `assets/reference/bear-trap/FINDINGS.md` apply  
- No gather/Discord scope in this plan  

---

## File structure

| File | Responsibility |
|------|----------------|
| `ks/cartograph/__init__.py` | Package export |
| `ks/cartograph/mask.py` | Fractional UI mask + crop |
| `ks/cartograph/project.py` | pixel↔world via MAT + viewport |
| `ks/cartograph/sweep.py` | Jump grid + swipe offsets; dry-run plan |
| `ks/cartograph/dedupe.py` | Merge structure hits |
| `ks/cartograph/labels.py` | Label OCR → StructureHit (stub ok first) |
| `ks/cartograph/pipeline.py` | Orchestrate fixture/live |
| `ks/cartograph/cli.py` | `ks cartograph` entry |
| `ks/device/bluestacks.py` | Discover/connect BlueStacks ADB |
| `scripts/bluestacks_connect.py` | Operator connect + smoke |
| `config/params.yaml` | `cartograph:` + optional serial |
| `tests/test_cartograph_*.py` | Unit tests |

---

### Task 1: Mask + project (offline)

**Files:**
- Create: `ks/cartograph/mask.py`
- Create: `ks/cartograph/project.py`
- Create: `tests/test_cartograph_mask.py`
- Create: `tests/test_cartograph_project.py`

- [ ] Write failing tests: mask blacks fractional rects and crops; project maps crop-center pixel to viewport world xy
- [ ] Implement mask from calibration-style fractional rects
- [ ] Implement `world_from_pixel(px, py, viewport, mat)` / inverse
- [ ] Run pytest for these files — expect pass

### Task 2: Sweep planner (dry-run)

**Files:**
- Create: `ks/cartograph/sweep.py`
- Create: `tests/test_cartograph_sweep.py`

- [ ] Write failing test: center (698,816), R=30, step=10 → grid covers bbox and includes center
- [ ] Implement `plan_jumps(cx, cy, radius, step)` + optional swipe offsets
- [ ] Run pytest — expect pass

### Task 3: Dedupe + footprint helpers

**Files:**
- Create: `ks/cartograph/dedupe.py`
- Create: `ks/cartograph/models.py`
- Create: `tests/test_cartograph_dedupe.py`

- [ ] Define `StructureHit(id, label, kind, x, y, w, h, source)`
- [ ] Dedupe hits within 1 tile + similar label; never merge distinct banner ids without flag
- [ ] Run pytest — expect pass

### Task 4: Pipeline fixture path + CLI

**Files:**
- Create: `ks/cartograph/pipeline.py`
- Create: `ks/cartograph/labels.py` (stub: empty list or heuristic later)
- Create: `ks/cartograph/cli.py`
- Modify: `ks/cli.py` or `pyproject.toml` scripts entry `ks-cartograph`
- Modify: `config/params.yaml`
- Create: `tests/test_cartograph_pipeline.py`

- [ ] Fixture pipeline: load PNGs + viewport YAML → mask → (stub labels ok) → emit YAML path
- [ ] CLI: `--radius`, `--dry-run`, `--fixture-dir`, `--out`, `--calibration`
- [ ] Dry-run prints jump plan without device
- [ ] Run pytest — expect pass

### Task 5: BlueStacks connect helper

**Files:**
- Create: `ks/device/bluestacks.py`
- Create: `scripts/bluestacks_connect.py`
- Create: `tests/test_bluestacks_connect.py` (mock adb)

- [ ] Try common ports / `adb devices`; `adb connect 127.0.0.1:port`
- [ ] Return serial string; optional write into params suggestion
- [ ] Script prints serial + calls smoke screencap when device present
- [ ] Unit test with mocked client — no live device required

### Task 6: Live viewport hook (when device online)

**Files:**
- Modify: `ks/cartograph/pipeline.py`
- Modify: `scripts/adb_smoke.py` (optional pointer to bluestacks_connect)

- [ ] Live mode: `AdbDevice.connect` → screencap → viewport OCR → dry-run plan or one sample
- [ ] Manual check: `python scripts/bluestacks_connect.py` then `ks-cartograph --dry-run`

### Task 7: Label OCR v0 (incremental)

**Files:**
- Modify: `ks/cartograph/labels.py`
- Create: `tests/test_cartograph_labels.py`

- [ ] Tesseract over cropped map band; regex for `[ALLI]` / city `NN` / Trap / Mill
- [ ] Kind inference + footprint table
- [ ] Fixture test on one batch3-cropped shot (skip if tesseract missing)

---

## Execution order

Tasks 1 → 2 → 3 → 4 → 5 immediately (offline).  
Task 6 when BlueStacks is up (~minutes).  
Task 7 can overlap after 4.
