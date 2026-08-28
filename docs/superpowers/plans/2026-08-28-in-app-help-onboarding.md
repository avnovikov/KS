# In-app help & step onboarding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a skippable 4-step setup wizard (Heroes → Gear → Troops → Governor charms) plus `/help` reference pages inside the KS FastAPI UI.

**Architecture:** Jinja2 step templates + shared stepper partial; `setup.js` owns `localStorage` progress; new routes in `app.py`; header links for Setup and Help; optional inventory nudge strips. Implement on branch cut from `feature/governor-optimiser-wire` (has Governor inventory subtab).

**Tech Stack:** Python 3.12+, FastAPI, Jinja2, vanilla JS, pytest + httpx TestClient.

**Spec:** `docs/superpowers/specs/2026-08-28-in-app-help-onboarding-design.md`

## Global Constraints

- Apple-light theme; reuse `app.css` tokens and layout patterns from `_layout.html`
- Step order fixed: **1 Heroes → 2 Gear → 3 Troops → 4 Governor charms**
- Wizard is **skippable**; never block inventory/optimiser routes
- Progress in `localStorage` key `ks.setup.v1` only (v1)
- Governor subtab label unchanged; copy may say “Governor charms”
- Work in git worktree under `.worktrees/feature-in-app-help-onboarding/`

---

## File map

| File | Action |
|------|--------|
| `ks/heroes/ui/templates/_layout.html` | Add Setup + Help header links |
| `ks/heroes/ui/templates/setup/_stepper.html` | New — step indicator |
| `ks/heroes/ui/templates/setup/_step_shell.html` | New — extends layout, includes stepper + footer |
| `ks/heroes/ui/templates/setup/step_heroes.html` … `step_governor.html` | New — step bodies |
| `ks/heroes/ui/templates/setup/done.html` | New — completion + Optimiser CTA |
| `ks/heroes/ui/templates/help/index.html` + `help_*.html` | New — reference chapters |
| `ks/heroes/ui/templates/_setup_nudge.html` | New — optional inventory strip |
| `ks/heroes/ui/static/setup.js` | New — progress + navigation helpers |
| `ks/heroes/ui/static/app.css` | Extend — stepper, step panel, nudge strip |
| `ks/heroes/ui/app.py` | Routes: `/setup/*`, `/help/*`, redirect logic |
| `tests/test_setup_onboarding.py` | New — route smoke + step content |

---

### Task 1: Worktree + route stubs

**Files:** worktree, `app.py`, stub templates

- [ ] Create worktree: `git worktree add -b feature/in-app-help-onboarding .worktrees/feature-in-app-help-onboarding feature/governor-optimiser-wire`
- [ ] Add failing tests: `GET /setup`, `/setup/1-heroes`, `/help` → 200
- [ ] Register routes returning minimal stub templates
- [ ] Run tests green

### Task 2: Step shell + stepper

**Files:** `_step_shell.html`, `_stepper.html`, `app.css`

- [ ] Stepper shows 1–4 with current step highlighted, completed = checkmark link
- [ ] Shell provides Back / Skip setup / Next footer slots
- [ ] Responsive at 390px width

### Task 3: Step content (four steps + done)

**Files:** `step_*.html`, `done.html`

- [ ] Copy from spec: titles, “Do this” bullets, deep links, tips
- [ ] Each step: primary “Open …” button to inventory route
- [ ] Done page: link to `/optimiser/events` and `/help`

### Task 4: Help reference pages

**Files:** `help/index.html`, `help_heroes.html`, …

- [ ] Hub lists four chapters + Optimiser overview
- [ ] Each chapter links back to matching `/setup/N-…`
- [ ] Header `?` → `/help`

### Task 5: setup.js progress

**Files:** `setup.js`, wire in step templates

- [ ] Read/write `ks.setup.v1` schema from spec
- [ ] Mark complete on button click; advance `current_step`
- [ ] Skip setup sets `skipped: true`
- [ ] `/setup` redirects to first incomplete step (client-side or server query)

### Task 6: Header + first-visit redirect

**Files:** `_layout.html`, `app.py`, `setup.js`

- [ ] Setup pill: “Step N of 4” or “Complete”
- [ ] Soft redirect to `/setup` once per session when incomplete (dismissible)
- [ ] Inventory nudge strip via `_setup_nudge.html` when step incomplete

### Task 7: Auto-complete hooks (optional v1)

**Files:** `inventory.js`, troops save handler, governor upgrade script

- [ ] Troops: on successful save, call `window.markSetupStep('troops')`
- [ ] Heroes/Gear/Governor: expose `markSetupStep` for manual + future hooks
- [ ] Document server-side `/api/setup/status` as v1.1 if deferred

### Task 8: Tests + manual smoke

- [ ] `test_setup_onboarding.py`: all routes 200, step bodies contain key phrases
- [ ] `pytest tests/test_setup_onboarding.py -v`
- [ ] Manual: phone-width browser, complete flow 1→4, skip path, help hub

---

## Test plan

```bash
cd .worktrees/feature-in-app-help-onboarding
source .venv/bin/activate  # or repo .venv
pip install -e '.[dev,ui]'
pytest tests/test_setup_onboarding.py -v
ks-heroes ui --gear data/gear/full-run --heroes data/heroes/full-run
# open http://127.0.0.1:8765/setup
```
