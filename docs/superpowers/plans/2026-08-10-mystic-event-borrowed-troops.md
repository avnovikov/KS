# Mystic event-borrowed troops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use TDD.

**Goal:** Stage·round UI + store for player event `tier` + `march_size`; mystic solvers use those instead of inventory troop mix/capacity.

**Architecture:** Extend `radiant_opponents` store + room YAML defaults; pass into `optimize_radiant` (Coliseum already wraps it); mirror GET/PUT + picker fields on Radiant and Coliseum pages.

**Tech stack:** Python, FastAPI, existing mystic trial YAML store, optimiser JS.

---

### Task 1: Store + room defaults

**Files:**
- Modify: `ks/heroes/optimize/mystic_trial/radiant_opponents.py`
- Modify: `ks/heroes/optimize/mystic_trial/rooms.py`
- Modify: `config/mystic_trial/coliseum.yaml`, `radiant_spire.yaml` (optional defaults)
- Test: `tests/test_radiant_opponents_store.py`, `tests/test_mystic_trial_rooms.py`

**Steps:** parse/get/upsert `player_event_troops`; room `event_troop_tier`; defaults 10 / 250000 helpers.

### Task 2: Solver

**Files:**
- Modify: `ks/heroes/optimize/radiant_spire.py`, `mystic_trial/coliseum.py`
- Test: `tests/test_radiant_spire.py`, `tests/test_coliseum_optimize.py`

**Steps:** accept `event_troop_tier` + capacity; pure-tier blend; engine `mc` when attrition used; Coliseum uses room event cap (not None).

### Task 3: API + UI

**Files:**
- Modify: `ks/heroes/ui/app.py`, `optimize_run.py`
- Modify: radiant/coliseum HTML+JS
- Test: API + UI smoke tests

**Steps:** PUT/GET event troops; optimize reads store; picker inputs; commit when green.
