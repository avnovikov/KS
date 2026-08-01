# Gear Inventory OCR Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or implement inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ks-heroes collect-gear` that dumps the full hero-gear warehouse (equipped + unequipped) via ADB+OCR into `artifacts/gear/<run>/gear.json`.

**Architecture:** Separate config (`config/gear.yaml`), models, parse, scrape-one-piece, page/cell collector, and store — mirrored from heroes collector patterns. Live ADB calibration fills coords before a full run.

**Tech Stack:** Python, ADB (`AdbDevice`), pytesseract via `ks.heroes.ocr_util`, pytest, YAML.

## Global Constraints

- ADB-first for taps/screenshots; verify transitions from screenshots.
- v1 fields: troop_type, slot, rarity, enhancement_level, mastery_level, equipped(+hero if readable), attack/defense/health/lethality.
- Do not change heroes collect/recommend behavior.
- Prefer nulls + raw_text over aborting on OCR failure.

## File Structure

- Create: `config/gear.yaml`
- Create: `ks/heroes/gear_models.py`, `gear_config.py`, `gear_parse.py`, `gear_scrape.py`, `gear_collector.py`, `gear_store.py`
- Modify: `ks/heroes/cli.py` — add `collect-gear`
- Create: `tests/test_gear_parse.py`, `tests/test_gear_store.py`, `tests/test_gear_collector.py`
- Artifacts: `artifacts/gear/calibration/`, `artifacts/gear/<run>/`

---

### Task 1: GearRecord model + parse_gear_detail (TDD)

**Files:**
- Create: `ks/heroes/gear_models.py`
- Create: `ks/heroes/gear_parse.py`
- Test: `tests/test_gear_parse.py`

**Produces:** `GearRecord`, `GearStats`, `parse_gear_detail(text) -> GearRecord` (page/index filled by caller)

- [ ] Write failing parse tests for enhancement/mastery/rarity/slot/troop/stats/equipped
- [ ] Implement models + parser
- [ ] Tests pass

### Task 2: GearStore

**Files:**
- Create: `ks/heroes/gear_store.py`
- Test: `tests/test_gear_store.py`

**Produces:** `GearStore.upsert` / `all_pieces` / `gear.json` (+ SQLite)

- [ ] Failing round-trip test
- [ ] Implement store
- [ ] Tests pass

### Task 3: Config loader + placeholder gear.yaml

**Files:**
- Create: `ks/heroes/gear_config.py`
- Create: `config/gear.yaml` (coords from calibration)

- [ ] Loader tests for required keys
- [ ] Implement loader
- [ ] Fill yaml after Task 4 calibration

### Task 4: Live ADB calibration

- [ ] Screenshot warehouse grid + open detail
- [ ] Measure cell taps and OCR boxes
- [ ] Write calibration shots under `artifacts/gear/calibration/`
- [ ] Update `config/gear.yaml`

### Task 5: Scrape one piece + collector loop

**Files:**
- Create: `ks/heroes/gear_scrape.py`, `ks/heroes/gear_collector.py`
- Test: `tests/test_gear_collector.py` (FakeDevice)

- [ ] Failing collector test with fake device
- [ ] Implement scrape + collect
- [ ] Tests pass

### Task 6: CLI `collect-gear`

**Files:**
- Modify: `ks/heroes/cli.py`

- [ ] Add subcommand `--config/--serial/--out/--dry-run/--save-screenshots`
- [ ] Wire AdbDevice + collect_gear
- [ ] Dry-run works without device

### Task 7: Device verification

- [ ] Short collect-gear run (1 page or few pieces)
- [ ] Spot-check JSON vs screen
