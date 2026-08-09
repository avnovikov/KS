# Radiant Spire + Governor Gear Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans. Steps use checkbox syntax.

**Goal:** Manual 6-slot governor gear inventory + Radiant Spire dual-march proxy optimiser (#39 + #40).

**Architecture:** `governor_*` modules mirror gear store (JSON+SQLite); Radiant proxy scorer consumes `governor_troop_bonuses()` + hero expedition; UI inventory page + optimiser segment.

**Tech Stack:** Python, FastAPI/Starlette UI already in `ks/heroes/ui`, YAML config, pytest.

**Spec:** `docs/superpowers/specs/2026-08-09-radiant-spire-governor-design.md`

## Global Constraints

- Manual only (no ADB scrape)
- Proxy first (no Monte Carlo / floor DB in this plan)
- 2 active marches; schema allows 3
- Work only in `.worktrees/feature-radiant-spire-governor`

---

### Task 1: Governor config + models + bonuses

**Files:** `config/governor_gear.yaml`, `ks/heroes/governor_config.py`, `ks/heroes/governor_models.py`, `ks/heroes/governor_bonuses.py`, `tests/test_governor_*.py`

- [ ] RED: ladder lookup, slot→troop, 3pc/6pc set bonus tests
- [ ] GREEN: implement config load + `governor_troop_bonuses`
- [ ] Commit

### Task 2: Governor store + upgrade API

**Files:** `ks/heroes/governor_store.py`, wire `app.py` GET/PATCH/POST upgrade, tests

- [ ] RED: upsert, upgrade one step, dual persist
- [ ] GREEN: store + API
- [ ] Commit

### Task 3: Governor inventory UI

**Files:** `inventory_governor_gear.html`, JS, `_subnav_inventory.html`

- [ ] RED/smoke: page 200, 6 slots, upgrade button hits API
- [ ] GREEN: UI
- [ ] Commit

### Task 4: Radiant proxy + dual-march ratio search

**Files:** `ks/heroes/optimize/radiant_spire.py`, tests

- [ ] RED: exclusive heroes, ratio grid, governor shifts score
- [ ] GREEN: scorer + search
- [ ] Commit

### Task 5: Radiant UI + optimize bundle hook

**Files:** `optimize_run.py` or dedicated route, optimiser template/JS, subnav

- [ ] Wire API + page showing 2 marches
- [ ] Tests smoke
- [ ] Commit

### Task 6: Verify

- [ ] Full pytest subset green; manual curl upgrade + optimize
