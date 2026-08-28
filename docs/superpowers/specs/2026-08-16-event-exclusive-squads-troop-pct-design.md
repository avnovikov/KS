# Event exclusive squads + troop % of capacity

**Date:** 2026-08-16  
**Status:** Approved  
**Branch:** `feature/swordland-garrison-exclusive`

## Goals

1. **Swordland:** Rally Lead then Garrison with the lead trio locked out of Garrison.
2. **Bear Trap:** Keep Joiner pool; add one-click **Joiner without Rally Lead** (roster − lead 3).
3. **Troop display:** Event lineup (and shared mystic `troopsLine`) show each type as **% of march capacity**, not headcounts.

## Behavior

### Swordland

- Solve `garrison` first (hold one attack-widget hero out of that pool for Rally Lead).
- Re-solve `rally_lead` on `roster − {garrison heroes}`.
- Other Sword modes (`joiner`, `solo`) unchanged (full roster).
- If either mode is infeasible after exclusion, surface `mode_errors` as today.

### Bear Trap

- Default Joiner still uses the full roster (overlap with Rally Lead allowed).
- **Joiner pool** unchanged (custom allow-list dialog).
- New button **Joiner without Rally Lead** (same bar as Joiner pool): POST `/api/optimize/beartrap/joiner` with `allow_heroes` = roster names minus Rally Lead trio; switch board to Joiner.

### Troop line

- Format: `I 48% · C 0% · A 52% · cap 80,245` (percent of `effective_capacity` / march `capacity`).
- Underfilled marches may sum under 100%.
- Zero capacity → `—` for percents; still show cap when known.
- Applies to Event lineups `optimiser_events.js` and mystic `optimiser_board.js` `troopsLine`.

## Out of scope

- Persisting the Bear exclusive toggle
- Exclusive gear across marches
- Changing Sword `joiner` / `solo` exclusivity
- Absolute troop counts elsewhere (inventory editor stays counts)

## Testing

- Unit: Swordland garrison names ∩ rally_lead names = ∅ when both optimal
- UI smoke: Joiner-without-lead control present; troopsLine uses `%`
