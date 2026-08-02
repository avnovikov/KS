# Heroes Gear UI (local FastAPI)

**Date:** 2026-08-01  
**Branch:** `feature/heroes-gear-ui`  
**Status:** Implemented (v1)

## Goal

Local web UI to inspect scraped hero gear and edit enhancement / mastery levels, persisting through `GearStore` (JSON + SQLite) so recommend/arena use the same inventory.

## Non-goals (v1)

- No Heroes / Arena pages
- Auth, multi-user, remote deploy
- Re-OCR on level edit (estimated power *is* recomputed on edit only — never on UI open)
- Creating / deleting individual pieces by hand (full replace via OCR rescan is supported)

## Stack

- FastAPI + Jinja2 + uvicorn (+ `httpx` for TestClient)
- Optional dependency group: `ui` (`fastapi`, `uvicorn`, `jinja2`)
- CLI: `ks-heroes ui --gear <dir> [--config gear.yaml] [--serial …] [--port 8765]`

## Routes

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/` | Redirect to `/gear` |
| GET | `/gear` | HTML table of pieces with edit controls + **Rescan from OCR** button |
| GET | `/api/gear` | JSON list (`icon_url` per piece) |
| POST | `/api/gear/rescan` | Clear inventory; ADB OCR walk of Backpack > Gear into the same gear dir (409 if already running) |
| GET | `/static/...` | Bundled gear-piece PNGs |
| GET | `/icons/...` | Per-inventory crops / SVG fallbacks |
| PATCH | `/api/gear/{piece_id}` | Body: `{enhancement_level?, mastery_level?, clear_enhancement?, clear_mastery?}` → upsert + estimated power |

## Validation

- `enhancement_level`: integer 0–200 inclusive, or omit; `clear_enhancement: true` / `null` clears
- `mastery_level`: integer 0–20 inclusive, or `null` / `clear_mastery: true` to clear
- Unknown `piece_id` → 404
- Writes via `GearStore.upsert` (frozen `GearRecord` replaced with `dataclasses.replace`)
- Power sync runs only after an explicit level edit when rarity + enhancement are known

## Persistence

Default gear dir: `artifacts/gear/full-run` (must exist or be passed). Updates touch both `gear.json` and `gear.db`.

## Testing

- Unit tests for PATCH validation and level persistence against a temp `GearStore`
- No browser e2e in v1
