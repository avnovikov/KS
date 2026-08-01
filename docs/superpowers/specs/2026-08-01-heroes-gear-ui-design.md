# Heroes Gear UI (local FastAPI)

**Date:** 2026-08-01  
**Branch:** `feature/heroes-gear-ui`  
**Status:** Approved for v1 implementation

## Goal

Local web UI to inspect scraped hero gear and edit enhancement / mastery levels, persisting through `GearStore` (JSON + SQLite) so recommend/arena use the same inventory.

## Non-goals (v1)

- Heroes / Arena pages (stubs / links only)
- Auth, multi-user, remote deploy
- Re-OCR or power recalculation on level edit
- Creating / deleting pieces

## Stack

- FastAPI + Jinja2 + uvicorn
- Optional dependency group: `ui` (`fastapi`, `uvicorn`, `jinja2`)
- CLI: `ks-heroes ui --gear <dir> [--port 8765]`

## Routes

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/` | Redirect to `/gear` |
| GET | `/gear` | HTML table of pieces with edit controls |
| GET | `/api/gear` | JSON list |
| PATCH | `/api/gear/{piece_id}` | Body: `{enhancement_level?, mastery_level?}` → upsert |

## Validation

- `enhancement_level`: integer 0–200 inclusive, or omit
- `mastery_level`: integer 0–20 inclusive, or `null` to clear
- Unknown `piece_id` → 404
- Writes via `GearStore.upsert` (frozen `GearRecord` replaced with `dataclasses.replace`)

## Persistence

Default gear dir: `artifacts/gear/full-run` (must exist or be passed). Updates touch both `gear.json` and `gear.db`.

## Testing

- Unit tests for PATCH validation and level persistence against a temp `GearStore`
- No browser e2e in v1
