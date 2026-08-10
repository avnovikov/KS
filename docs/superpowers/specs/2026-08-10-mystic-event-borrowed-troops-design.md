# Mystic Trial event-borrowed troops (tier + march size)

**Date:** 2026-08-10  
**Status:** Approved for implementation  
**Branch / worktree:** `feature/radiant-floor-selector` · `.worktrees/feature-radiant-floor-selector`

## Problem

Mystic Trial marches (Radiant Spire, Coliseum) borrow event troops. The optimiser currently blends **inventory** `troops.yaml` for unit stats and (for Coliseum) fill capacity. That understates fight strength when the event supplies a fixed top tier and march size.

Radiant already has room-level `event_march_capacity` for fill size, but still blends inventory tiers. Coliseum forced `event_march_capacity=None`.

## Decision

Per **stage · round** (same setup as opponents), the player enters:

| Field | Meaning | Range / default |
|-------|---------|-----------------|
| `tier` | Event top troop tier (pure, all types) | 1–11; default **10** |
| `march_size` | Event march capacity / fill size | ≥ 1; default **250000** |

Persist under the room opponents YAML:

`governor/.../mystic_trial/{radiant|coliseum}_opponents.yaml`  
→ `stages[stage][round].player_event_troops: { tier, march_size }`

Room YAML may supply defaults (`event_troop_tier`, `event_march_capacity`) used when a stage·round has no saved override.

## Solver behaviour

When resolving a mystic optimize with stage·round (or room defaults):

1. **Unit stats:** pure `troop_stats[type][tier][truegold]` — **not** inventory mix. `truegold` still comes from inventory YAML (unchanged).
2. **Fill:** `event_march_capacity = march_size`; owned pool = `march_size` per type (independent marches, same as current Radiant event-cap path).
3. **Opponents:** unchanged (their levels/counts/bonuses).
4. **Engine label:** `mc` when opponent attrition MC runs (complete saved opponents or floor stub); else `proxy`.

Coliseum stops forcing inventory capacity; it uses the same event-troop path as Radiant.

## UI (Radiant + Coliseum)

In the stage·round picker row: **Troop tier** and **March size** inputs.

- Shown once stage+round are set (with opponent draft).
- Persist via Apply on a small “Event troops” control, or dedicated save; load with opponent GET.
- Generate sends stage/round; server loads saved `player_event_troops` (falling back to room defaults / 10 + 250000).

## API

- Extend GET opponents payload with `player_event_troops`.
- `PUT .../event-troops/{stage}/{round}` body `{ tier, march_size }` (Radiant + Coliseum paths).
- Optimize already keyed by stage/round; read store and pass into `optimize_radiant` / `optimize_coliseum`.

## Out of scope

- Molten Fort UI (same store fields later if needed).
- Editing truegold in mystic setup.
- Changing inventory Troops page.

## Acceptance

- With tier=10, march_size=250000 and complete opponents, Coliseum/Radiant Generate uses T10 unit stats and 250k fill; inventory T6 counts do not affect mystic unit blend.
- Values round-trip in `{room}_opponents.yaml` per stage·round.
- Incomplete opponents still proxy; complete opponents run MC and report engine `mc` when attrition is used.
