# Conquest in Event lineups UI — design

**Date:** 2026-08-02  
**Branch / worktree:** `feature/conquest-formation-optimizer`  
**Depends on:** `2026-08-02-conquest-formation-optimizer-design.md` (math + CLI)

## Goal

Surface the existing Conquest formation optimiser on the Event lineups page, alongside Swordland / Bear Trap / Arena. Math-only optimiser already exists; this wires it into the UI.

## Decision

**Event lineups only** (not Gear XP target dropdown). New **Conquest** block under Arena, same 2F+3B board pattern as Arena attack/defense.

## Design

### Backend — `ks/heroes/ui/optimize_run.py`

- After Arena solve, load `config/conquest_roles.yaml` via `load_combat_roles`
- Call `optimize_conquest(..., gear=gear, gear_profile=gear_profile_arena)`
- Set `bundle["conquest"]` to `CombatFormationResult.to_dict()` (includes `mode: conquest`)
- On failure, same error-shaped dict as an Arena side (`status`, empty formation, `error`)
- `attach_gear_icon_urls` also patches `bundle["conquest"].gear_assignment`

### API

`GET /api/optimize` JSON gains:

```json
"conquest": { "mode": "conquest", "formation": {...}, "heroes": [...], "score": ..., "status": "...", "gear_assignment": ... }
```

Partial failure for Conquest must not break Sword/Bear/Arena sections (`errors.conquest`).

### UI — `optimize_events.html`

- New section `#conquest-block` below Arena
- Header meta: mention Conquest
- Reuse Arena formation render (2F+3B) for the single Conquest result
- Regenerate all includes Conquest; optional section regen button

### Out of scope

- Gear XP `conquest` event target
- Separate Conquest explainability beyond Arena-style reasons already on the result
- New visual design language

## Testing

- Unit/API: `run_optimize_bundle` includes `conquest` key with 5-slot formation when heroes ≥ 5
- Existing Arena/Sword/Bear tests stay green
