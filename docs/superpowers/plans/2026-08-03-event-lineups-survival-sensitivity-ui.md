# Event lineups survival + sensitivity UI — Implementation Plan

> **For agentic workers:** TDD; work only in `.worktrees/feature-conquest-formation-optimizer`.

**Goal:** Wire survival + sensitivity B into Arena/Conquest Event lineups API + UI.  
**Spec:** `docs/superpowers/specs/2026-08-03-event-lineups-survival-sensitivity-ui-design.md`

## File map

| File | Role |
|------|------|
| `ks/heroes/optimize/sensitivity.py` | Build variants + win_summary |
| `ks/heroes/optimize/survival_pipeline.py` | Call sensitivity from `attach_survival` |
| `ks/heroes/optimize/combat_formation.py` | Promote `survival` in `to_dict` |
| `ks/heroes/ui/templates/optimize_events.html` | Render survival + sensitivity |
| `tests/test_heroes_sensitivity.py` | Unit tests |
| `tests/test_heroes_optimize_ui.py` or hardening | Bundle includes sensitivity |

## Tasks

### Task 1: Sensitivity module (TDD)

1. Write failing tests for `build_sensitivity` (baseline Δ=0, swap changes F1/F2, variants have score_eff).
2. Implement `sensitivity.py`.
3. Wire into `attach_survival`; promote survival on CombatFormationResult.
4. Verify tests green.

### Task 2: UI

1. Extend `renderFormationCard` + modal with survival/sensitivity.
2. Manual smoke via `/api/optimize` if server available; else unit-level payload check.

### Task 3: Bundle test

1. Assert arena/conquest Optimal payloads include `survival.sensitivity` (or top-level sensitivity inside survival).
