# Heroes Inventory + Optimiser UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the local heroes UI into an Apple-light, phone-ready **Inventory | Optimiser** shell with Gear/Heroes/Troops inventory, Event lineups + Gear XP tools, trust cues after OCR, and redirects from legacy paths.

**Architecture:** Keep FastAPI + Jinja2 + vanilla JS. Extract shared Apple chrome into layout partials. Add a small `TroopStore` so optimisers read UI-edited troops instead of only repo `config/troops.yaml`. Restyle existing gear/heroes/optimize templates; Event lineups become mode-chips + formation board; Gear XP stays single-column; Hero levels ships as a placeholder subtab.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, uvicorn, pytest + httpx TestClient, existing `GearStore` / `HeroStore` / `optimize_run` / `spend_xp`.

**Spec:** `docs/superpowers/specs/2026-08-02-heroes-inventory-optimiser-ui-design.md`

**Worktree:** Implement on `feature/heroes-gear-xp` (or a branch cut from it) inside `.worktrees/feature-heroes-roster-ui`.

## Global Constraints

- Apple light only: canvas `#f5f5f7`, panels `#fff`, text `#1d1d1f`, muted `#6e6e73`/`#86868b`, border `#d2d2d7`, accent `#0071e3`, ok `#34c759`, warn `#ff9f0a`, err `#ff3b30`.
- Font stack: `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif`.
- Primary nav: **Inventory** · **Optimiser** (underline). Subtabs: segmented control.
- Inventory subtabs: Gear · Heroes · Troops. Optimiser subtabs: Event lineups · Gear XP · Hero levels (placeholder).
- Phone-first: `viewport-fit=cover`, `env(safe-area-inset-*)`, ≥44px tap targets, subtabs horizontally scrollable under 640px.
- No OCR evidence crops in v1 (parking lot). No forced verification gate. No dark theme.
- Gear XP remains propose-only (no auto-write to `gear.json`).
- TDD for Python/API helpers; HTML changes covered by TestClient route/redirect/smoke tests.
- Do not invent Hero levels solver algorithm in this plan — placeholder page only.
- Prefer small focused modules; if `app.py` grows further, extract route modules only when a task explicitly says so.

## File map

| Path | Role |
|------|------|
| `ks/heroes/ui/templates/_layout.html` | Shared Apple chrome, primary tabs, flash/toast slot |
| `ks/heroes/ui/templates/_subnav_inventory.html` | Gear / Heroes / Troops segmented subtabs |
| `ks/heroes/ui/templates/_subnav_optimiser.html` | Event lineups / Gear XP / Hero levels subtabs |
| `ks/heroes/ui/static/app.css` | Shared Apple + responsive CSS (extracted from inline) |
| `ks/heroes/ui/static/inventory.js` | Auto-save, filters, trust highlights helpers |
| `ks/heroes/ui/troop_store.py` | Load/save UI troops YAML/JSON; seed from config |
| `ks/heroes/ui/trust.py` | Diff previous vs current inventory for row flags |
| `ks/heroes/ui/templates/inventory_gear.html` | Replaces/restyles gear table |
| `ks/heroes/ui/templates/inventory_heroes.html` | Replaces/restyles heroes table |
| `ks/heroes/ui/templates/inventory_troops.html` | Troops editor |
| `ks/heroes/ui/templates/optimiser_events.html` | Layout B formation board |
| `ks/heroes/ui/templates/optimiser_gear_xp.html` | Layout A Apple restyle |
| `ks/heroes/ui/templates/optimiser_hero_levels.html` | Placeholder |
| `ks/heroes/ui/app.py` | New routes + redirects + troops wiring |
| `ks/heroes/ui/optimize_run.py` | Accept `troops_path` from app (already path-based) |
| `tests/test_heroes_inventory_optimiser_ui.py` | Nav, redirects, troops API, trust helpers |
| Legacy templates (`gear.html`, `heroes.html`, `optimize_*.html`) | Delete or thin-wrap redirect after cutover |

---

### Task 1: Shared Apple layout + CSS + route skeleton

**Files:**
- Create: `ks/heroes/ui/static/app.css`
- Create: `ks/heroes/ui/templates/_layout.html`
- Create: `ks/heroes/ui/templates/_subnav_inventory.html`
- Create: `ks/heroes/ui/templates/_subnav_optimiser.html`
- Modify: `ks/heroes/ui/app.py` (mount `/static` already exists; add new inventory/optimiser routes that render stub pages; redirects from legacy paths)
- Create: `ks/heroes/ui/templates/inventory_gear.html` (minimal stub extending layout)
- Create: `ks/heroes/ui/templates/inventory_heroes.html` (stub)
- Create: `ks/heroes/ui/templates/inventory_troops.html` (stub)
- Create: `ks/heroes/ui/templates/optimiser_events.html` (stub)
- Create: `ks/heroes/ui/templates/optimiser_gear_xp.html` (stub)
- Create: `ks/heroes/ui/templates/optimiser_hero_levels.html` (stub)
- Test: `tests/test_heroes_inventory_optimiser_ui.py`

**Interfaces:**
- Produces routes:
  - `GET /inventory/gear`, `/inventory/heroes`, `/inventory/troops`
  - `GET /optimiser/events`, `/optimiser/gear-xp`, `/optimiser/hero-levels`
  - `GET /` → `/inventory/gear` if gear configured else `/inventory/heroes`
  - Legacy: `/gear`→`/inventory/gear`, `/heroes`→`/inventory/heroes`, `/optimize`→`/optimiser/events`, `/optimize/events`→`/optimiser/events`, `/optimize/gear-xp`→`/optimiser/gear-xp`
- Layout context keys: `primary` (`inventory`|`optimiser`), `subtab` (string), `gear_enabled`, `heroes_enabled`

- [ ] **Step 1: Write failing redirect/nav tests**

```python
from pathlib import Path
from fastapi.testclient import TestClient
from ks.heroes.ui.app import create_app

def _client(tmp_path: Path, *, with_gear=True, with_heroes=True) -> TestClient:
    gear = heroes = None
    if with_gear:
        gear = tmp_path / "gear"
        gear.mkdir()
        (gear / "gear.json").write_text("[]", encoding="utf-8")
    if with_heroes:
        heroes = tmp_path / "heroes"
        heroes.mkdir()
        (heroes / "heroes.json").write_text("[]", encoding="utf-8")
    return TestClient(create_app(gear_dir=gear, heroes_dir=heroes))

def test_home_redirects_to_inventory_gear(tmp_path):
    c = _client(tmp_path)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/inventory/gear"

def test_legacy_gear_redirects(tmp_path):
    c = _client(tmp_path)
    r = c.get("/gear", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/inventory/gear"

def test_inventory_gear_page_has_apple_shell(tmp_path):
    c = _client(tmp_path)
    r = c.get("/inventory/gear")
    assert r.status_code == 200
    assert "Inventory" in r.text and "Optimiser" in r.text
    assert "#f5f5f7" in r.text or "app.css" in r.text
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /Users/alexei/KS/.worktrees/feature-heroes-roster-ui
python -m pytest tests/test_heroes_inventory_optimiser_ui.py::test_home_redirects_to_inventory_gear -v
```

Expected: FAIL (404 or old redirect to `/gear`)

- [ ] **Step 3: Add `app.css` + layout partials + stub pages + routes/redirects**

`app.css` must include safe-area padding, primary underline tabs, segmented subtabs with `overflow-x: auto` under 640px, 44px min tap targets, table sticky first column helpers.

`_layout.html` structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>{% block title %}KS{% endblock %}</title>
  <link rel="stylesheet" href="/static/app.css" />
</head>
<body>
  <header class="app-header">
    <div class="brand">KS</div>
    <nav class="primary-nav" aria-label="Primary">
      <a href="/inventory/gear" class="{% if primary == 'inventory' %}on{% endif %}">Inventory</a>
      <a href="/optimiser/events" class="{% if primary == 'optimiser' %}on{% endif %}">Optimiser</a>
    </nav>
    <div class="header-actions">{% block actions %}{% endblock %}</div>
  </header>
  {% if primary == 'inventory' %}{% include "_subnav_inventory.html" %}{% endif %}
  {% if primary == 'optimiser' %}{% include "_subnav_optimiser.html" %}{% endif %}
  <main>{% block content %}{% endblock %}</main>
  <div id="toast" hidden></div>
  {% block scripts %}{% endblock %}
</body>
</html>
```

Wire stubs in `create_app` and keep existing `/api/*` endpoints working (do not remove APIs).

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/test_heroes_inventory_optimiser_ui.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ks/heroes/ui/static/app.css ks/heroes/ui/templates/_layout.html \
  ks/heroes/ui/templates/_subnav_inventory.html ks/heroes/ui/templates/_subnav_optimiser.html \
  ks/heroes/ui/templates/inventory_*.html ks/heroes/ui/templates/optimiser_*.html \
  ks/heroes/ui/app.py tests/test_heroes_inventory_optimiser_ui.py
git commit -m "$(cat <<'EOF'
feat(heroes-ui): add Apple-light Inventory/Optimiser shell and redirects

EOF
)"
```

---

### Task 2: TroopStore + troops API + Optimiser reads UI troops

**Files:**
- Create: `ks/heroes/ui/troop_store.py`
- Modify: `ks/heroes/ui/app.py` (GET/PUT troops pages + API; `app.state.troops_path`)
- Modify: `ks/heroes/ui/optimize_run.py` (ensure `run_optimize_bundle` already takes `troops_path`; app must pass store path)
- Modify: gear-xp API handler in `app.py` to pass same `troops_path`
- Test: `tests/test_heroes_inventory_optimiser_ui.py` (extend)

**Interfaces:**
- Produces:
  - `class TroopStore`:
    - `__init__(self, path: Path, *, seed_from: Path | None = None)`
    - `path: Path`
    - `load_raw(self) -> dict[str, Any]`
    - `save_raw(self, data: dict[str, Any]) -> dict[str, Any]`  # validates via `troops_config_from_dict`
    - `ensure_exists(self) -> None`  # copy seed if missing
  - `GET /api/troops` → raw dict + totals
  - `PUT /api/troops` body = troops YAML-shaped JSON → saved dict
- Consumes: `ks.heroes.optimize.troops.troops_config_from_dict`, `load_troops_config`

Troops file location: `{heroes_dir}/troops.yaml` if heroes configured, else `{gear_dir}/troops.yaml`. Seed from repo `config/troops.yaml` on first ensure.

- [ ] **Step 1: Write failing TroopStore + API tests**

```python
from ks.heroes.ui.troop_store import TroopStore
from ks.heroes.optimize.troops import load_troops_config

def test_troop_store_seeds_and_roundtrips(tmp_path, repo_troops: Path):
    dest = tmp_path / "troops.yaml"
    store = TroopStore(dest, seed_from=repo_troops)
    store.ensure_exists()
    raw = store.load_raw()
    assert "march_capacity" in raw
    raw["march_capacity"] = 90000
    saved = store.save_raw(raw)
    assert saved["march_capacity"] == 90000
    cfg = load_troops_config(dest)
    assert cfg.march_capacity == 90000

def test_put_troops_rejects_negative(tmp_path):
    # create app with heroes dir; PUT negative infantry tier → 422
    ...
```

Use a fixture path to the worktree `config/troops.yaml`.

- [ ] **Step 2: Run — expect FAIL**

```bash
python -m pytest tests/test_heroes_inventory_optimiser_ui.py -k troop -v
```

- [ ] **Step 3: Implement `TroopStore` + wire `app.state.troops_path` + GET/PUT `/api/troops`**

Validation errors → HTTP 422 with message string. `save_raw` must reject unknown shapes the same way `troops_config_from_dict` does.

Update optimize + gear-xp handlers:

```python
troops_path = app.state.troops_path  # Path
# pass into run_optimize_bundle / spend_xp entrypoints
```

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit**

```bash
git add ks/heroes/ui/troop_store.py ks/heroes/ui/app.py ks/heroes/ui/optimize_run.py \
  tests/test_heroes_inventory_optimiser_ui.py
git commit -m "$(cat <<'EOF'
feat(heroes-ui): persist editable troops inventory for optimisers

EOF
)"
```

---

### Task 3: Inventory Troops page (Apple form)

**Files:**
- Modify: `ks/heroes/ui/templates/inventory_troops.html`
- Optional: `ks/heroes/ui/static/troops.js`
- Test: HTML smoke in `tests/test_heroes_inventory_optimiser_ui.py`

**Interfaces:**
- Consumes: `GET/PUT /api/troops`
- UI fields: `march_capacity`, `truegold`, and per-type tier grid (levels 1–11) matching YAML shape; show per-type **total** as read-only sum

- [ ] **Step 1: Write smoke test**

```python
def test_troops_page_renders_form(tmp_path):
    c = _client(tmp_path)
    r = c.get("/inventory/troops")
    assert r.status_code == 200
    assert "march_capacity" in r.text or "March" in r.text
```

- [ ] **Step 2: Run — expect FAIL if stub empty**
- [ ] **Step 3: Implement phone-friendly form**

- Sticky bottom **Save** not required if auto-save on blur; use debounced PUT like inventory JS will.
- On narrow screens, one troop type per section (accordion or stacked cards), not a huge 3×11 matrix squeezed.

- [ ] **Step 4: Manual check** — `ks-heroes ui --heroes … --gear …` open `/inventory/troops`, change a tier, reload, value persists; run `/api/optimize` and confirm troops totals moved.
- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(heroes-ui): Apple troops inventory editor

EOF
)"
```

---

### Task 4: Trust diff helpers + post-rescan banners

**Files:**
- Create: `ks/heroes/ui/trust.py`
- Modify: gear/heroes rescan handlers in `app.py` to return `trust` summary in JSON
- Modify: inventory templates/JS to apply row classes from `sessionStorage` trust payload
- Test: `tests/test_heroes_inventory_optimiser_ui.py`

**Interfaces:**
- Produces:
  - `flag_gear_rows(before: list[GearRecord], after: list[GearRecord]) -> dict[str, str]`
    - map `piece_id` → `"new" | "changed" | "incomplete"`
  - `flag_hero_rows(before: list[HeroRecord], after: list[HeroRecord]) -> dict[str, str]`
    - map hero name → same flags
  - Incomplete gear: `enhancement_level is None` or (`rarity` in epic/mythic/red and `mastery_level is None`) — keep heuristic in one function docstring
  - Incomplete hero: `stars is None` or `power is None`

Rescan API response adds:

```json
{
  "count": 42,
  "trust": {
    "flags": {"piece-or-name": "changed"},
    "new": 2,
    "changed": 3,
    "incomplete": 1
  },
  "cache_bust": "…"
}
```

- [ ] **Step 1: Unit tests for flag helpers**

```python
from ks.heroes.ui.trust import flag_gear_rows
from ks.heroes.gear_models import GearRecord

def test_flag_new_and_changed_gear():
    before = [GearRecord(piece_id="a", name="A", enhancement_level=10, mastery_level=1, rarity="epic")]
    after = [
        GearRecord(piece_id="a", name="A", enhancement_level=12, mastery_level=1, rarity="epic"),
        GearRecord(piece_id="b", name="B", enhancement_level=None, mastery_level=None, rarity="epic"),
    ]
    flags = flag_gear_rows(before, after)
    assert flags["a"] == "changed"
    assert flags["b"] in {"new", "incomplete"}
```

(Adjust `GearRecord` construction to match real required fields in this repo.)

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement `trust.py`; snapshot before rescan; attach flags to response**
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(heroes-ui): post-rescan trust flags for inventory rows

EOF
)"
```

---

### Task 5: Inventory Gear + Heroes Spreadsheet+ (Apple)

**Files:**
- Create: `ks/heroes/ui/static/inventory.js`
- Rewrite: `ks/heroes/ui/templates/inventory_gear.html`
- Rewrite: `ks/heroes/ui/templates/inventory_heroes.html`
- Modify: `app.py` template names for `/inventory/*` to pass pieces/heroes + icons (reuse existing page logic from old `/gear` `/heroes` handlers)
- Keep PATCH APIs unchanged (`/api/gear/{id}`, `/api/heroes/{name}`)
- Test: extend existing `tests/test_heroes_gear_ui.py` / `tests/test_heroes_roster_ui.py` for redirects; add auto-save not required server-side

**Behavior:**
- Filter chips: All / Needs attention / troop types; name search
- Sortable columns (port existing JS)
- Auto-save: `input` debounce 400ms → PATCH; remove Save buttons
- Apply `data-trust` row classes from `sessionStorage` after rescan; clear flag for a row after successful PATCH; **Mark all reviewed** clears storage
- Banner with counts + soft link to `/optimiser/events`
- Sticky first column; horizontal scroll on narrow

- [ ] **Step 1: Port old gear/heroes handler bodies to `/inventory/gear` and `/inventory/heroes` rendering new templates; leave redirects on old paths**
- [ ] **Step 2: Implement `inventory.js` auto-save + filters + trust banner**
- [ ] **Step 3: Run UI-related pytest modules**

```bash
python -m pytest tests/test_heroes_gear_ui.py tests/test_heroes_roster_ui.py tests/test_heroes_inventory_optimiser_ui.py -v
```

- [ ] **Step 4: Manual phone-width check** (browser devtools 390×844): edit enh, rescan banner visible, tabs tappable
- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(heroes-ui): Apple Spreadsheet+ gear and heroes inventory

EOF
)"
```

---

### Task 6: Optimiser Event lineups — layout B

**Files:**
- Rewrite: `ks/heroes/ui/templates/optimiser_events.html` (port logic from `optimize_events.html`)
- Modify: `app.py` `/optimiser/events` + keep `/api/optimize`
- Optional extract: `ks/heroes/ui/static/optimiser_events.js`
- Test: smoke `GET /optimiser/events` 200; `GET /api/optimize` still 200 with heroes fixture

**UI structure:**
1. Event segmented control: Swordland | Bear Trap | Arena
2. Mode chips grid (points/score on each); selected chip highlighted
3. Formation board for selection: Front row (F1–F2 or 3-hero event layout), Back row when arena; portraits from `/static/heroes/{slug}.webp` or API icon urls if present
4. Troops + points meta on board
5. Hero tap → bottom sheet (phone) / modal (wide): why + gear grid (reuse existing modal JS)
6. Refresh button in header actions

For non-arena modes without F/B formation, show ordered hero portraits in a single row labeled March.

- [ ] **Step 1: Write smoke test for events page + api**

```python
def test_optimiser_events_page(tmp_path):
    c = _client(tmp_path)
    assert c.get("/optimiser/events").status_code == 200
```

- [ ] **Step 2: Port and restyle JS from `optimize_events.html` into layout B**
- [ ] **Step 3: Run optimize-related tests**

```bash
python -m pytest tests/test_heroes_optimize_ui.py tests/test_heroes_inventory_optimiser_ui.py -v
```

(If test module name differs, use existing optimize UI test file(s) in `tests/`.)

- [ ] **Step 4: Manual: load events, switch modes, open hero sheet on narrow viewport**
- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(heroes-ui): Apple event lineups board (mode chips + formation)

EOF
)"
```

---

### Task 7: Optimiser Gear XP — Apple single column + troops path

**Files:**
- Rewrite: `ks/heroes/ui/templates/optimiser_gear_xp.html` (from `optimize_gear_xp.html`)
- Modify: `app.py` `/optimiser/gear-xp` + ensure POST uses `app.state.troops_path`
- Test: existing gear-xp tests still pass; add redirect test `/optimize/gear-xp` → `/optimiser/gear-xp`

**UI:** Event target controls → fodder count inputs (grey/green/blue/purple/100pt) → pill **Find best spends** → delta line → spend rows → leftovers. Optional link: `/optimiser/events` .

- [ ] **Step 1: Redirect + page smoke tests**
- [ ] **Step 2: Restyle template to Apple CSS variables/classes; keep POST contract identical**
- [ ] **Step 3: Run**

```bash
python -m pytest tests/ -k "gear_xp or spend_xp or inventory_optimiser" -v
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(heroes-ui): Apple Gear XP optimiser page under /optimiser

EOF
)"
```

---

### Task 8: Hero levels placeholder + cleanup legacy templates

**Files:**
- Finalize: `ks/heroes/ui/templates/optimiser_hero_levels.html`
- Delete or stub-deprecate: `gear.html`, `heroes.html`, `optimize.html`, `optimize_hub.html`, `optimize_events.html`, `optimize_gear_xp.html`, `_nav_tabs.html` once nothing references them
- Modify: CLI print URLs in `app.py` / `cli.py` to new paths
- Test: assert placeholder copy present; legacy redirects still work

Placeholder copy:

```text
Hero levels — coming next
Recommend which heroes to push for a chosen event.
Solver design is tracked separately; this subtab reserves the IA.
```

- [ ] **Step 1: Tests for placeholder + CLI URL strings if asserted**
- [ ] **Step 2: Implement placeholder; remove dead templates; grep for old template names**
- [ ] **Step 3: Full relevant suite**

```bash
python -m pytest tests/test_heroes_gear_ui.py tests/test_heroes_roster_ui.py \
  tests/test_heroes_inventory_optimiser_ui.py tests/test_heroes_optimize_ui.py \
  tests/test_heroes_spend_xp.py -v
```

- [ ] **Step 4: Manual acceptance checklist from spec** (Inventory↔Optimiser chrome, 390px flows, trust cues, subtab extensibility)
- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(heroes-ui): hero-levels placeholder and remove legacy UI templates

EOF
)"
```

---

## Self-review vs spec

| Spec item | Task |
|-----------|------|
| Primary Inventory \| Optimiser + underline shell A | Task 1 |
| Subtabs Gear/Heroes/Troops + Event/Gear XP/Hero levels | Task 1, 3, 6–8 |
| Apple light + phone safe areas / 44px / sticky column | Task 1, 5, 6 |
| Spreadsheet+ auto-save, filters, trust banner | Task 4, 5 |
| Troops store + optimiser shared source | Task 2, 3 |
| Event lineups layout B | Task 6 |
| Gear XP layout A | Task 7 |
| Hero levels reserved | Task 8 |
| Legacy redirects | Task 1 |
| Parking lot / OCR evidence deferred | Explicitly not tasked |
| No dark theme / no forced gate | Global constraints |

## Out of scope (do not implement here)

- OCR evidence crops UI
- Hero levels solver algorithm
- Review-queue wizard
- Applying Gear XP spends into inventory
- Native app

---

## Agent / LLM recommendation

| Role | Model | Why |
|------|--------|-----|
| **Lead implementer (recommended)** | **Claude Opus 4.7 or Opus 5** (high/thinking) | Best fit for cohesive Apple UI across many Jinja/CSS/JS files, tasteful responsive layout, and sticking to a long multi-task plan without drifting into dark-admin patterns |
| Backend-heavy tasks (TroopStore, trust diffs) | Claude Sonnet 4/5 or GPT-5.6 | Faster/cheaper for TDD Python modules if split via subagent-driven-development |
| Avoid as sole owner | Composer fast / Haiku / Grok fast | Fine for tiny patches; weak at keeping visual system + IA consistent across 8 tasks |

**Execution style:** Prefer **subagent-driven-development** with Opus on Tasks 1, 5, 6 (UI chrome) and Sonnet/GPT on Tasks 2–4 (stores/tests). One agent doing all 8 inline also works if using Opus end-to-end.

**Do not** ask a fast model to “just restyle the HTML” without the plan — that is how the current dark tables proliferated.
