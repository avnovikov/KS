# Radiant Spire — layered optimiser + MC utility

**Date:** 2026-08-09  
**Branch:** `feature/radiant-floor-selector`  
**Status:** Approved — implementing  
**Supersedes (partial):** stub-only `combat_mc.simulate_floor` as ranking objective when floor set

## Goal

Separate **search** (combinatorial decisions) from **utility** (fight evaluation).  
MC (or later tick sim) only scores a candidate; the engine proposes and keeps the best.

## Architecture

```text
RadiantSearch
  ├─ lineup layer   : assign 3 heroes / march (1 per troop), exclusive across marches
  ├─ gear layer     : exclusive mythic/owned sets per lineup (v1); neighbourhood later
  ├─ troop layer    : capacity knapsack via ratio grid (published + step grid)
  └─ evaluate(x)    : fight utility → win_rate (mean over trials)
```

### Decision variables (candidate `x`)

| Variable | Constraint |
|----------|------------|
| `hero_names[3]` | Catalog heroes; v1 one per troop type |
| `gear_by_hero` | Exclusive sets from inventory |
| `counts` | Sum ≤ event/inventory capacity; non‑neg ints |
| `ratio` | Derived from counts (for display) |

### Utility

`evaluate(player_state, enemy_state, *, trials, seed) -> UtilityResult`

v1 fight model: **multi-round troop attrition** with light stochasticity  
(offense/tough from existing `score_march` components; each round deals damage  
proportional to offense with noise; wipe or round cap → win/loss + remaining HP).

Not in v1 utility: full skill/tick/AoE (tracked as v1.1 utility swap — same API).

### Search policy (v1)

1. Greedy / top‑K lineups (reuse current one-per-troop pick).  
2. Assign exclusive gear once per lineup.  
3. Grid-search ratios; **if a troop type has a hero in the lineup, that type’s ratio share ≥ `min_hero_troop_share` (default 0.05)** so cavalry heroes cannot pair with 0 cavalry.  
4. Rank by mean `win_rate` over `trials` (default small, e.g. 32) when enemy/floor present; else proxy score.

## Out of scope (this slice)

PuLP ILP for Radiant, pets/charms, full skill tick sim, OCR foes.

## Files

| File | Role |
|------|------|
| `mystic_trial/fight_utility.py` | Attrition MC evaluate API |
| `mystic_trial/combat_mc.py` | Thin adapter / deprecate stub ranking |
| `mystic_trial/radiant_search.py` | Layered search orchestration |
| `radiant_spire.py` | Call search engine |
| tests | Utility + search constraints + integrate |
