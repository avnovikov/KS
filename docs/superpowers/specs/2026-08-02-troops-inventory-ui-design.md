# Troops Inventory UI

**Date:** 2026-08-02  
**Branch:** `feature/heroes-gear-ui` (same FastAPI inventory app)  
**Status:** Approved — ready for implementation plan

## Goal

Local web page to view and edit manual troop inventory (`config/troops.yaml`) the same way Gear and Heroes inventory screens work: Jinja page, JSON list API, per-cell `PATCH` + Save, toast feedback, shared tab bar. Optimize continues to load the same YAML.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Host | Same FastAPI app as Gear / Heroes / Optimize |
| Layout | Wrapping tile grid per type (~6 tiles/row); three sections: Infantry, Cavalry, Archers |
| Tiers shown | Always T1–T11; zeros dimmed but editable |
| Editable | Per type×tier `count`; header `march_capacity` |
| Not editable | `truegold` (YAML-only; leave value untouched on writes) |
| Save UX | Per-tile Save (type×tier) + separate Save for march capacity — same pattern as Gear/Heroes rows |
| Rescan / OCR | Out of scope for v1 |
| Icons | Vendored type×tier images under `ks/heroes/ui/static/troops/`; SVG tier-badge fallback if missing |
| Persistence | Read/write repo `config/troops.yaml` (same file Optimize uses) |

## Non-goals (v1)

- OCR / ADB troop rescan
- Editing `truegold` in the UI
- Creating/deleting troop *types* (fixed infantry / cavalry / archers)
- Standalone troops mini-app or Optimize-only panel

## Stack

- FastAPI + Jinja2 + uvicorn (existing `ui` optional group)
- Shared `_nav_tabs.html` chrome and dark theme tokens from Gear/Heroes pages
- CLI: existing `ks-heroes ui …` — no new required flag; troops path defaults to repo `config/troops.yaml` (optional `--troops` only if needed later)

## Routes

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/troops` | HTML page (`troops.html`); `Cache-Control: no-store` |
| GET | `/api/troops` | JSON: `march_capacity`, type blocks with levels 1–11 + `icon_url` + type totals |
| PATCH | `/api/troops/march-capacity` | Body `{ march_capacity }` → update capacity (register **before** the type/tier route) |
| PATCH | `/api/troops/{type}/{tier}` | Body `{ count }` → update that cell in YAML |
| GET | `/static/troops/…` | Vendored icons (via existing `/static` mount) |

Nav: add **Troops inventory** tab in `_nav_tabs.html` (enabled whenever the UI process is running; does not require `--gear` / `--heroes`).

`GET /` redirect order unchanged (gear if configured, else heroes). Troops is reached via the tab.

## UI layout

- Same header / tab / toast / button styling as Gear and Heroes.
- Header: title, path to `troops.yaml`, march capacity number input + Save, optional per-type totals in meta line.
- Body: three panels (Infantry / Cavalry / Archers). Each panel is a wrapping CSS grid of tiles.
- Tile: small icon, `T{n}` label, count `<input type="number" min="0">`, **Save** button.
- Zero counts: muted/dimmed tile chrome; still fully editable.
- No Rescan button.

## Validation

- `type`: one of `infantry`, `cavalry`, `archers` (YAML key `archers`); unknown → 404
- `tier`: integer 1–11 inclusive; else 404
- `count`: non-negative integer; else 400
- `march_capacity`: non-negative integer; else 400
- Writes must preserve `truegold` (and prefer preserving comments/header when practical)

## Persistence

- Load via existing `load_troops_config` / raw YAML for round-trip fields (`truegold`).
- Small write helper: load mapping → set field → dump YAML (stable key order: `march_capacity`, `truegold`, then type blocks with keys 1–11).
- After save, Optimize and other callers see updates on next `load_troops_config`.

## Icons

- Path convention: `ks/heroes/ui/static/troops/{type}-t{n}.webp`  
  Examples: `infantry-t6.webp`, `cavalry-t1.webp`, `archers-t11.webp`
- Vendor from a public Kingshot data site (same private-tooling practice as gear/heroes); document source + date in `ks/heroes/ui/static/ATTRIBUTION.md`.
- Resolution: bundled static file if present → otherwise generated tier-badge SVG (letter/color by type + `Tn`).
- UI serves URLs like `/static/troops/infantry-t6.webp` (cache-bust query optional, same helper as other inventories if useful).

## Testing

- TestClient: `GET /troops` → 200; nav contains Troops tab
- `GET /api/troops` returns levels 1–11 for each type and icon URLs
- `PATCH` count persists to a temp `troops.yaml` and round-trips
- `PATCH` march-capacity persists; `truegold` unchanged
- Invalid type/tier/count → 404/400 as specified
- No browser e2e in v1

## Out of scope follow-ups

- Optional `--troops PATH` CLI override
- Hide-empty-tiers toggle
- Editable `truegold`
- OCR inventory capture
