# Bear Trap — Joiner pool selector

**Date:** 2026-08-15  
**Branch:** `feature/beartrap-joiner-pool`  
**Status:** Approved  

## Goal

When running **both** a Rally Lead (starter) and a Joiner march the same day, let the player pick a **Joiner pool** of heroes (default: roster minus the three Rally Lead heroes) via a selector button, then re-solve Joiner with only that allow-list.

## Decisions

| Topic | Choice |
|-------|--------|
| UX | Button **Joiner pool** after Rally Lead is feasible |
| Default pool | All roster heroes except the three on Rally Lead |
| API | Extend optimize path: re-run joiner with `hero_allowlist` (or filter heroes client→server) |
| Persistence | None in v1 (Regenerate clears custom pool) |
| Errors | Clear message if pool cannot form a valid 3-hero joiner lineup |

## API shape

`POST /api/optimize/beartrap/joiner` (or query on existing optimize):

```json
{ "allow_heroes": ["Helga", "Saul", "Diana", "..."] }
```

Server: filter roster to those names (must exist), `recommend(..., force_mode="joiner")`.

Alternatively keep `GET /api/optimize` for initial load; button calls a dedicated endpoint so Rally Lead is unchanged.

## UI

- Bear Trap segment: **Joiner pool** next to Joiner chip when Rally Lead mode has `hero_names`
- Dialog: checkboxes for remaining heroes; Confirm → fetch joiner-only result → replace Joiner chip/board data
- Lead trio shown disabled or omitted

## Out of scope

- Pre-assigning starter locks before first solve
- localStorage persistence
- Placement map seats

## Testing

- Unit: filtering heroes then joiner recommend excludes lead names
- API: allowlist missing troop coverage → 400
- UI smoke: control present in optimiser_events markup/JS
