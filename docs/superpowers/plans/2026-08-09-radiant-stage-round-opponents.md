# Radiant stage·round opponents — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Radiant Spire opponents by stage·round·slot (level, counts, bonuses) on Apply and reload them on optimize.

**Architecture:** Small YAML store beside `governor_dir`; merge into opponent panel when `stage`+`round` are set; PUT API for Apply; UI Stage/Round fields replace Floor.

**Tech Stack:** Python, YAML, FastAPI, existing Radiant JS/HTML.

**Spec:** `docs/superpowers/specs/2026-08-09-radiant-stage-round-opponents-design.md`

## Global Constraints

- UI/API copy: **stage** / **round** (not floor); accept `floor` query as deprecated alias for stage.
- Apply auto-saves selected opponent slot only.
- Proxy-only when stage or round unset.

---

### Task 1: Opponent YAML store

**Files:**
- Create: `ks/heroes/optimize/mystic_trial/radiant_opponents.py`
- Test: `tests/test_radiant_opponents_store.py`

- [x] Failing tests: load empty, upsert slot, round-trip levels/counts/bonuses, two slots independent
- [x] Implement load/save/upsert helpers
- [x] Tests pass

### Task 2: Merge into optimize + API

**Files:**
- Modify: `ks/heroes/ui/optimize_run.py`, `ks/heroes/optimize/radiant_spire.py` (merge helper if needed)
- Modify: `ks/heroes/ui/app.py` — `stage`/`round` params, PUT endpoint, store path from `governor_dir`
- Test: `tests/test_radiant_ui.py` / new API tests

- [x] Optimize merges saved marches when stage+round set
- [x] PUT upserts slot then round-trip via GET optimize
- [x] Tests pass

### Task 3: UI Stage/Round + Apply saves

**Files:**
- Modify: `optimiser_radiant_spire.html`, `.js`, floor UI tests → stage/round
- [x] Replace Floor select with Stage + Round inputs
- [x] Apply → PUT then reload optimize with stage/round
- [x] Tests pass

### Task 4: Spec status + smoke

- [x] Mark design spec Status: Implemented
- [x] Run radiant-related pytest
