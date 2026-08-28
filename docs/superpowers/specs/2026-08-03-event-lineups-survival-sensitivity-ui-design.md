# Event lineups: survival + sensitivity UI (5-hero)

**Date:** 2026-08-03  
**Branch / worktree:** `feature/conquest-formation-optimizer`  
**Status:** Approved for implementation (sensitivity scope **B**)  
**Depends on:** `2026-08-03-arena-front-survival-opponent-models-design.md`

## Goal

Surface front-survival vs self-play foes on Arena attack/defense and Conquest in Event lineups, plus **sensitivity B**: gear-claim variants and F1↔F2 swap, with **Δscore_eff** and short “how you win/lose” copy.

## Decision

- Expand `/api/optimize` payloads (approach 1): each 5-hero result already runs survival; attach a small `sensitivity` block in the same response.
- UI: enrich Arena/Conquest cards + detail modal. Sword/Bear unchanged.
- Out of scope: ±% pressure knobs, full 120 gear-order enum, Gear XP page.

## Backend

### Promote survival

- Arena already puts `survival` on `to_dict()`.
- Conquest `CombatFormationResult.to_dict()` also promotes `explanations.survival` → top-level `survival`.

### Sensitivity (`ks/heroes/optimize/sensitivity.py`)

Called from `attach_survival` after primary foe eval. Variants (fixed formation unless noted):

| id | Change |
|----|--------|
| `baseline` | Current formation + mode gear order |
| `gear_f2_first` | Claim order starts with F2 (Howard when F2) |
| `gear_back_first` | `B2,B1,B3,F1,F2` |
| `swap_front` | F1↔F2, same gear order |
| `swap_front_f1_gear` | F1↔F2, then F1 claims gear first |

Each variant: `id`, `label`, `formation`, `score_eff`, `s`, `tau_F`, `delta_score_eff` (vs baseline), `delta_s`, optional `blurb`.

Also top-level:

- `win_summary`: 1–3 sentences vs primary foe (`s`, backline discount, foe front names, best alternate Δ).
- `primary_foe`: model name used for deltas.

## UI (`optimize_events.html`)

On each Arena/Conquest card (when `survival` present):

1. Score line: ILP + **score_eff** + **s**
2. Compact foe rows: model, foe front, `s`, `score_eff`
3. Sensitivity: ranked non-baseline variants with green/red Δ
4. `win_summary` text

Modal: same survival/sensitivity block above per-hero gear.

## Testing

- Unit: sensitivity deltas vs baseline; swap changes formation; `win_summary` non-empty when foes exist.
- UI/API: `run_optimize_bundle` arena/conquest include `survival` + `sensitivity` when gear/heroes allow Optimal.
