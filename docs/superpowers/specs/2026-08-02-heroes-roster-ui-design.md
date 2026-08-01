# Heroes Roster UI (stars / pellets + star-scaled power)

**Date:** 2026-08-02  
**Branch:** `feature/heroes-roster-ui` (from `feature/heroes-gear-ui`)  
**Status:** Approved — ready for implementation

## Goal

Local web page to update hero **stars** and **pellets** during events without re-OCR, so recommend/arena keep using current star progress. When stars/pellets change, **naked power is derived** from the last OCR baseline via `star_progress_factor`. Optional **Rescan from OCR** refreshes the roster from ADB when you have time.

## Power model (star factor)

Web databases do **not** publish usable naked Power-by-stars tables. What they publish is combat ATK/DEF/HP and exclusive-weapon Power — not the ungeared hero Power number from detail OCR.

Community “star power” multipliers (≈50%→100% across the star strip) match the intent of our existing:

```text
star_progress_factor(stars, pellets) → [0.5, 1.0]
```

(`ks/heroes/optimize/scoring.py`: progress = stars + pellets/6, capped at 5; factor = 0.4 + 0.12×progress.)

**Derivation on edit:**

```text
power′ = round(power × f(stars′, pellets′) / f(stars, pellets))
```

- Skip rescale if `power` is missing, or if old factor ≤ 0.
- OCR / rescan always **overwrites** absolute `power` (and stars/pellets from vision).
- Do **not** invent absolute power without a stored OCR baseline.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Host | Same FastAPI app as gear UI |
| Editable | `stars` (0–5), `pellets` (0–5) only |
| Power | Display + auto-update via star factor on PATCH; not manually editable |
| Rescan | `POST /api/heroes/rescan` → `collect_heroes` upsert (no full wipe); 409 if busy |
| Icons | Prefer vendored portraits from [kingshotdata.com](https://kingshotdata.com/) `/uploads/…/{slug}.webp`; fallback `names/` crop; else letter SVG |
| Persistence | `HeroStore` → `heroes.json` + SQLite |
| Nav | Header links: Gear \| Heroes when both dirs configured |

## Routes

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/` | Redirect to `/gear` if gear configured, else `/heroes` |
| GET | `/heroes` | HTML table: icon, name, troop, stars, pellets, power (derived), Save |
| GET | `/api/heroes` | JSON list (+ icon URLs) |
| PATCH | `/api/heroes/{name}` | `{stars?, pellets?}` → upsert + rescale power |
| POST | `/api/heroes/rescan` | ADB OCR roster refresh (409 if busy) |
| GET | `/static/heroes/…` | Vendored portraits |

Gear routes unchanged when `--gear` is set.

## CLI

```bash
ks-heroes ui --heroes artifacts/heroes/full-run --gear artifacts/gear/full-run [--port 8878]
```

- `--heroes` optional; required for `/heroes` routes.
- `--gear` optional; required for `/gear` routes.
- At least one of `--heroes` / `--gear` must exist with its JSON file.
- `--config` remains gear.yaml for gear rescan; heroes rescan uses `config/heroes.yaml` (add `--heroes-config` if needed).

## Icons

- Slug: lowercase name, spaces → hyphens (e.g. `Long Fei` → `long-fei`).
- Try paths: `ks/heroes/ui/static/heroes/{slug}.webp` then common upload date folders if vendoring script used.
- Vendor into `ks/heroes/ui/static/heroes/` + ATTRIBUTION note (private tooling use).
- Resolution order: bundled static → `HeroStore.names_dir` crop → letter SVG.

## Validation

- `stars`: integer 0–5  
- `pellets`: integer 0–5 (UI in-progress slot; OCR may store 0–6)  
- Unknown name → 404  
- Rescan requires ADB + heroes config; upsert merges — manual stars remain until OCR overwrites that hero  

## Out of scope (v1)

- Editing level, escorts, rarity, skills  
- Absolute power formula without OCR baseline  
- Arena page  
- Auth / remote deploy  

## Testing

- Unit: PATCH stars/pellets persists; power scales by `star_progress_factor` ratio  
- Unit: missing power → stars update, power stays null  
- Unit: out-of-range stars/pellets → 400  
- Smoke: `/heroes` renders; rescan mocked  
- Regression: gear routes still work when both dirs set  
