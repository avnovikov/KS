# Hero Levels Spend Optimizer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allocate a Hero EXP bag across roster levels to maximize event utility (Sword/Bear/Arena), with UI mirroring Gear XP on `/optimiser/hero-levels`.

**Architecture:** Knapsack outer search (greedy marginal ΔU) over +1 hero levels; inner \(U\) reuses event solvers with gear fixed and heroes mutated. Power rescale uses scraped deployment-capacity factors as \(f(L)\) (published with XP costs; no public naked-power-vs-level table).

**Tech Stack:** Python, FastAPI, Jinja2, YAML config, pytest.

**Worktree:** `.worktrees/feature-heroes-inventory-ui` on `feature/heroes-inventory-optimiser-ui`.

## Global Constraints

- Propose only (no auto-write to `heroes.json`)
- Single EXP total input (not typed packs)
- Lineups unlocked (re-run event solver after tentative levels)
- Config under `config/hero_level_optimizer/` with source URL + date
- Skip heroes missing `level` or `power`

---

### Task 1: Scraped level tables + power rescale

**Files:**
- Create: `config/hero_level_optimizer/README.md`
- Create: `config/hero_level_optimizer/hero_level_xp_costs.yaml`
- Create: `config/hero_level_optimizer/hero_level_power.yaml`
- Create: `ks/heroes/optimize/hero_level_ladder.py`
- Modify: `ks/heroes/ui/hero_power.py` (add `scale_power_for_level_change`)
- Test: `tests/test_heroes_hero_level_ladder.py`, `tests/test_heroes_level_power.py`

**Interfaces:**
- Produces: `load_hero_level_ladder() -> dict` with `max_level`, `by_level[L] = {xp_cost, power_factor}`; `xp_cost_next_hero_level(ladder, current_level) -> int | None`; `level_power_factor(ladder, level) -> float`; `scale_power_for_level_change(power, old_L, new_L, ladder=...) -> int | None`

- [ ] **Step 1:** Write failing tests for ladder load, xp between levels, power rescale ratio
- [ ] **Step 2:** Add YAML from https://ks.h5joy-games.com/guides/hero-level/ (2026-08-02): `xp_cost` to reach each level 1–80; `power_factor` = deployment capacity from same table
- [ ] **Step 3:** Implement ladder helpers + `scale_power_for_level_change`
- [ ] **Step 4:** pytest pass; commit

### Task 2: `spend_hero_xp` allocator

**Files:**
- Create: `ks/heroes/optimize/spend_hero_xp.py`
- Test: `tests/test_heroes_spend_hero_xp.py`

**Interfaces:**
- Consumes: Task 1 ladder + rescale; event utility over heroes
- Produces: `allocate_hero_exp(heroes, gear, hero_exp, event, mode?, ...) -> HeroSpendResult`; `build_hero_event_utility(event, gear, ...) -> Callable[[list[HeroRecord]], tuple[float, dict]]`

- [ ] **Step 1:** Failing tests with stubbed \(U\) (prefer hero A over B)
- [ ] **Step 2:** Implement greedy +1 search mirroring `spend_xp.allocate_fodder_xp`
- [ ] **Step 3:** pytest pass; commit

### Task 3: API + Optimiser UI

**Files:**
- Modify: `ks/heroes/ui/app.py` — `POST /api/optimize/hero-levels`
- Rewrite: `ks/heroes/ui/templates/optimiser_hero_levels.html` (Gear XP shape, Apple shell)
- Modify: `tests/test_heroes_inventory_optimiser_ui.py` (smoke API + page)

- [ ] **Step 1:** Failing route/API tests
- [ ] **Step 2:** Wire API + template (event select, hero_exp, Find best spends, results table)
- [ ] **Step 3:** pytest pass; commit

## Spec coverage

| Spec item | Task |
|-----------|------|
| Scraped XP + power tables | 1 |
| Power rescale ratio | 1 |
| Knapsack / greedy ΔU | 2 |
| Same events as Gear XP | 2–3 |
| Unlocked lineups | 2 |
| UI = Gear XP layout | 3 |
| `POST /api/optimize/hero-levels` | 3 |
| Propose only | 3 |
