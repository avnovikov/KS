# Gear XP Spend Optimizer — Implementation Plan

> **For agentic workers:** Use TDD; commit after each coherent task.

**Goal:** Allocate grey/green/blue/purple + 100-pt fodder across gear to maximize event utility (recommend/arena), with Optimize hub + `/optimize/gear-xp` UI.

**Architecture:** XP ladder + typed fodder bag helpers; greedy marginal-ΔU search calling existing event solvers; FastAPI hub + gear-xp form/API.

**Tech Stack:** Python, PyYAML, PuLP (via existing solvers), FastAPI/Jinja2.

## Global Constraints

- Fodder XP: grey 10, green 30, blue 60, purple 150, 100-pt part 100 (`fodder_xp_values`)
- Caps from `enhancement_xp_costs.yaml`; typed bag (no type conversion)
- v1: enhancement only; propose spends (no auto-write); one event per run

### Task 1: XP ladder + fodder bag

**Files:** Create `ks/heroes/optimize/xp_ladder.py`, `tests/test_heroes_xp_ladder.py`

- Load ladder/caps/fodder values
- `xp_cost_to_reach(from_level, to_level)`, `cap_for_rarity`
- `FodderBag` with `can_cover(cost) -> spend_plan | None` (greedy largest-first)

### Task 2: Spend search maximizing U

**Files:** Create `ks/heroes/optimize/spend_xp.py`, `tests/test_heroes_spend_xp.py`

- `evaluate_event_utility(...)` → float + lineup summary
- `allocate_fodder_xp(...)` greedy: repeatedly pick feasible next-level step with best ΔU
- Apply levels + `compute_gear_power` when rarity known

### Task 3: UI hub + gear-xp

**Files:** Modify `app.py`, `_nav_tabs.html`; create `optimize_hub.html`, `optimize_gear_xp.html`; move event page or keep `/optimize/events`

- Hub at `/optimize`; event lineups at `/optimize/events` (redirect old `/optimize` → hub or keep events at `/optimize` and hub at `/optimize/` — per spec: events stay `/optimize`, gear at `/optimize/gear-xp`, so hub needs a landing — use `/optimize` as hub and move events to `/optimize/events` with redirect from old bookmarks via query? Spec says events `/optimize` and gear `/optimize/gear-xp`. Hub cards: make `/optimize` a hub that links to `/optimize/events` and `/optimize/gear-xp`, and relocate current optimize page to `/optimize/events`.

### Task 4: Wire API + tests + commit

`POST /api/optimize/gear-xp`; smoke tests; push.
