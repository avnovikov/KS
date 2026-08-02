# Troops Inventory UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add `/troops` inventory page matching Gear/Heroes patterns (Jinja + per-cell PATCH + toast), backed by `config/troops.yaml`.

**Architecture:** Small YAML inventory helper (`troops_inventory.py`) for load/patch/write; `troop_icons.py` for static/SVG URLs; extend `create_app` / nav / `troops.html`.

**Tech Stack:** FastAPI, Jinja2, PyYAML, pytest TestClient.

## Global Constraints

- Editable: type×tier counts + `march_capacity`; preserve `truegold`.
- Always show T1–T11; wrapping tile grid; per-tile Save.
- Match Gear/Heroes chrome; no OCR rescan in v1.
- TDD: failing test before production code per task.

---

### Task 1: Troops YAML inventory helper

**Files:**
- Create: `ks/heroes/ui/troops_inventory.py`
- Test: `tests/test_heroes_troops_ui.py`

**Interfaces:**
- `TYPE_KEYS = ("infantry", "cavalry", "archers")`
- `TIERS = range(1, 12)`
- `load_inventory(path) -> dict` with `march_capacity`, `truegold`, full 1–11 maps
- `set_count(path, troop_type, tier, count) -> dict`
- `set_march_capacity(path, capacity) -> dict`

- [x] Failing tests for load/normalize, set_count, set_march_capacity preserves truegold, validation
- [x] Implement helper
- [x] Tests pass

### Task 2: Troop icons helper

**Files:**
- Create: `ks/heroes/ui/troop_icons.py`
- Modify: `ks/heroes/ui/static/ATTRIBUTION.md`
- Test: same test file

- [x] Failing test: URL for missing icon is `/static/troops/…svg` (or webp if present)
- [x] Implement + ATTRIBUTION note
- [x] Tests pass

### Task 3: FastAPI routes + nav + template

**Files:**
- Modify: `ks/heroes/ui/app.py`, `ks/heroes/ui/templates/_nav_tabs.html`
- Create: `ks/heroes/ui/templates/troops.html`
- Modify: `ks/heroes/cli.py` / `run_ui` for default `troops_path`
- Test: `tests/test_heroes_troops_ui.py`

- [x] Failing TestClient tests for page, GET API, PATCH count, PATCH capacity, nav tab
- [x] Implement routes/template/nav
- [x] Tests pass

### Task 4: Verify full suite slice

- [x] `pytest tests/test_heroes_troops_ui.py tests/test_heroes_roster_ui.py::test_inventory_tabs_link_both_screens -v`
