# Heroes Roster UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/heroes` to the FastAPI UI so stars/pellets are editable and naked power rescales via `star_progress_factor`.

**Architecture:** Extend `create_app` / `run_ui` to accept optional `heroes_dir` alongside `gear_dir`. Pure helpers for power scaling and hero PATCH live next to gear helpers. Heroes rescan upserts via `collect_heroes` without wiping the store.

**Tech Stack:** FastAPI, Jinja2, HeroStore, pytest + TestClient, existing `star_progress_factor`.

## Global Constraints

- Stars UI range 0–5; pellets UI range 0–5.
- Power never manually editable; only OCR overwrite or star-factor rescale.
- At least one of gear/heroes inventory must be configured.
- Match existing gear UI dark theme and rescan UX patterns.
- TDD: failing test before production code per task.

---

### Task 1: Star-scaled power helper + HeroStore.reload

**Files:**
- Create: `ks/heroes/ui/hero_power.py`
- Modify: `ks/heroes/store.py` (add `reload`)
- Test: `tests/test_heroes_roster_ui.py`

**Interfaces:**
- Produces: `scale_power_for_star_change(power, old_stars, old_pellets, new_stars, new_pellets) -> int | None`
- Produces: `HeroStore.reload() -> None`

- [x] **Step 1: Write failing tests**

```python
from ks.heroes.optimize.scoring import star_progress_factor
from ks.heroes.ui.hero_power import scale_power_for_star_change

def test_scale_power_uses_star_progress_ratio():
    old_s, old_p, new_s, new_p = 2, 0, 3, 0
    power = 1_000_000
    expected = round(
        power
        * star_progress_factor(new_s, new_p)
        / star_progress_factor(old_s, old_p)
    )
    assert scale_power_for_star_change(power, old_s, old_p, new_s, new_p) == expected

def test_scale_power_none_stays_none():
    assert scale_power_for_star_change(None, 1, 0, 2, 0) is None
```

- [ ] **Step 2: Run tests — expect FAIL (import/missing)**
- [ ] **Step 3: Implement helper + `HeroStore.reload`**
- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

---

### Task 2: `update_hero_stars` persistence + power rescale

**Files:**
- Modify: `ks/heroes/ui/app.py` (or small `ks/heroes/ui/heroes_api.py` if cleaner)
- Test: `tests/test_heroes_roster_ui.py`

**Interfaces:**
- Produces: `update_hero_stars(store, name, *, stars=..., pellets=...) -> HeroRecord`
- Consumes: `scale_power_for_star_change`, `HeroStore.upsert`

- [ ] **Step 1: Failing tests** — PATCH helper scales power; out-of-range raises; unknown name KeyError
- [ ] **Step 2: Implement `update_hero_stars`**
- [ ] **Step 3: Tests PASS + commit**

---

### Task 3: FastAPI heroes routes + template + icons

**Files:**
- Modify: `ks/heroes/ui/app.py`, `ks/heroes/ui/__init__.py`
- Create: `ks/heroes/ui/templates/heroes.html`
- Create: `ks/heroes/ui/hero_icons.py`
- Modify: `ks/heroes/ui/static/ATTRIBUTION.md`
- Create: `ks/heroes/ui/heroes_rescan.py`
- Modify: `ks/heroes/cli.py` (`--heroes`, `--heroes-config`)
- Test: `tests/test_heroes_roster_ui.py`

**Interfaces:**
- `create_app(gear_dir=None, *, heroes_dir=None, ...)`
- `GET /heroes`, `GET/PATCH /api/heroes…`, `POST /api/heroes/rescan`
- `ensure_hero_icon(hero, heroes_dir) -> str` (URL path)

- [ ] **Step 1: Failing TestClient tests** for list/patch/page + mocked rescan
- [ ] **Step 2: Implement routes, template, icons, rescan, CLI**
- [ ] **Step 3: Full suite slice PASS + commit**

---

### Task 4: Wire gear↔heroes nav + docs

**Files:**
- Modify: `ks/heroes/ui/templates/gear.html` (nav link when heroes enabled)
- Modify: `docs/superpowers/specs/2026-08-02-heroes-roster-ui-design.md` (already written — verify)

- [ ] **Step 1: Nav links both ways**
- [ ] **Step 2: `pytest tests/test_heroes_gear_ui.py tests/test_heroes_roster_ui.py -v`**
- [ ] **Step 3: Commit**

## Spec coverage

| Spec item | Task |
|-----------|------|
| Star-factor power on PATCH | 1–2 |
| `/heroes` + APIs | 3 |
| Rescan upsert | 3 |
| Icons order | 3 |
| CLI `--heroes` | 3 |
| Gear regression | 4 |
