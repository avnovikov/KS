# Radiant layered optimiser + MC utility — Implementation Plan

> **For agentic workers:** Implement task-by-task; TDD; worktree `feature/radiant-floor-selector`.

**Goal:** Search engine proposes candidates; attrition MC is `evaluate` only. Stop 0% troop when that troop’s hero is present.

**Spec:** `docs/superpowers/specs/2026-08-09-radiant-layered-optimiser-design.md`

## Task 1: Fight utility (attrition MC)

**Files:** `ks/heroes/optimize/mystic_trial/fight_utility.py`, `tests/test_fight_utility.py`

- [ ] Failing tests: stronger offense wins more often; `trials` affects variance but mean in [0,1]; deterministic with seed
- [ ] Implement `evaluate_attrition(player: MarchScore, enemy: MarchScore, *, trials, rounds, seed) -> UtilityResult`
- [ ] Pass tests

## Task 2: Search — ratio grid with min hero-troop share

**Files:** `ks/heroes/optimize/mystic_trial/radiant_search.py`, `tests/test_radiant_search.py`

- [ ] Failing test: best ratio never has cavalry=0 when lineup includes a cavalry hero
- [ ] `ratio_candidates_for_lineup(troops_present, published, step, min_share)`
- [ ] `search_best_ratio(..., evaluate=...)` returns best counts/ratio/utility
- [ ] Pass tests

## Task 3: Wire into `optimize_radiant`

**Files:** `radiant_spire.py`, `combat_mc.py` (adapter), existing radiant tests

- [ ] Use search + fight utility when floor/enemy present
- [ ] `engine: "mc"` when utility used; expose `mc.trials`
- [ ] Regression: event capacity + opponent proxy still green; new test for non-zero cav

## Task 4: Restart UI smoke (manual)

- [ ] UI on :8770; stage/round with saved foes; ratios show cavalry when cav hero present
