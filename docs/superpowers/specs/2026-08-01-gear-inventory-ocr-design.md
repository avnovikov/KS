# Gear Inventory OCR Collector — Design

**Date:** 2026-08-01  
**Status:** Implemented (v1) — enhancement/mastery badge OCR still best-effort  
**Scope:** Separate ADB+OCR dump of the full hero-gear warehouse (equipped + unequipped)

## Decisions (brainstorming)

| Topic | Choice |
|-------|--------|
| What to capture | Full owned inventory, not only pieces shown on hero detail |
| How to run | Separate CLI: `ks-heroes collect-gear` |
| Fields (v1) | Identity + ATK/DEF/HP/Lethality |
| Calibration | Live ADB first — discover UI, then lock `config/gear.yaml` |
| Collection method | Tap each inventory cell → OCR detail panel → page/swipe |

Out of scope for v1: grid-only OCR without opening detail; exclusive-gear scrape on hero detail; wiring gear into role recommend / optimizer; Governor gear.

## Architecture

```
ks-heroes collect-gear
  → load config/gear.yaml
  → navigate to (or assume) gear warehouse
  → for each grid page:
       for each cell:
         tap → wait → screencap → OCR detail → parse → close
       swipe / next page
  → stop on empty page or max_pages
  → persist artifacts/gear/<run>/gear.json (+ optional SQLite)
```

Reuse existing heroes ADB helpers, `ocr_util` (crop → upscale → Otsu → pytesseract), and roster paging patterns. Do **not** bolt this into `scrape_hero`. New modules under `ks/heroes/` (or `ks/gear/` if it grows), new config file, new store.

### Phases

1. **Calibrate (blocking):** Live ADB — open warehouse, screenshot empty/full grid and one open detail panel; write nav taps, grid cell coords, OCR boxes, delays into `config/gear.yaml`.
2. **Implement collector** against calibrated config.
3. **Verify** on device with a short dry/full run; fix parsers/regions as needed.

## Data model

One record per physical inventory piece:

```json
{
  "piece_id": "page0-cell3",
  "troop_type": "infantry",
  "slot": "chest",
  "rarity": "mythic",
  "enhancement_level": 80,
  "mastery_level": 7,
  "equipped": true,
  "equipped_hero": null,
  "stats": {
    "attack": 12.5,
    "defense": 8.0,
    "health": 15.2,
    "lethality": 10.1
  },
  "raw_text": "...",
  "inventory_page": 0,
  "inventory_index": 3,
  "scraped_at": "2026-08-01T15:00:00+00:00",
  "detail_screenshot": "details/page0-cell3.png"
}
```

Rules:

- `troop_type`: `infantry` | `cavalry` | `archers` (normalize to heroes convention).
- `slot`: `helmet` | `chest` | `gloves` | `boots`.
- `rarity`: grey/green/blue/purple/mythic/red (map UI synonyms: gold→mythic).
- `enhancement_level` / `mastery_level`: ints; null if OCR fails.
- `equipped` / `equipped_hero`: from detail UI if readable; else `equipped` null and omit hero.
- `stats`: floats or ints as shown; keep `raw_text` for debug.
- Identity key for upsert: prefer stable UI id if found; else `(troop_type, slot, rarity, enhancement_level, mastery_level, inventory_page, inventory_index)` for that run. v1 store is run-scoped JSON; SQLite optional mirror of heroes store.

## Config (`config/gear.yaml`)

Mirror `heroes.yaml` shape:

- `adb.serial`
- `nav`: warehouse entry (if automated), back/close detail, page swipe
- `grid.cells[]`: tap points for inventory slots (like roster)
- `ocr`: boxes for rarity, enhancement, mastery, troop_type, slot, equipped line, stats panel (or per-stat boxes)
- `delays`: after tap, after close, after swipe
- `max_pages`, optional `max_pieces`

Exact coords filled during live calibration — placeholders allowed until then.

## Components

| Unit | Responsibility |
|------|----------------|
| `config/gear.yaml` + loader | Nav, grid, OCR regions, delays |
| `GearRecord` model | Frozen dataclass + to/from dict |
| `parse_gear_detail` | Regex/heuristics on OCR text → fields |
| `scrape_gear_piece` | One cell: tap, shot, OCR, parse, close |
| `collect_gear` | Page/cell loop, empty-page stop, persist |
| `GearStore` | Write `gear.json` (+ optional SQLite) |
| CLI `collect-gear` | `--config`, `--serial`, `--out`, `--dry-run`, `--save-screenshots` |

## Error handling

- Missing detail after tap: skip cell, log warning, continue (empty slot or mis-tap).
- Parse partial: store nulls + `raw_text`; do not abort run.
- Leave warehouse unexpectedly: stop run with clear error (ADB-first: verify via screenshot before continuing pages).
- Dismiss blocking popups with corner `X` when detected (same policy as heroes).

## Testing

- Unit: `parse_gear_detail` on fixture OCR strings / cropped PNGs from calibration.
- Unit: store round-trip JSON.
- Integration (manual/device): short `collect-gear` on 1 page after calibration; spot-check JSON vs screen.

## Success criteria

- One command dumps all reachable warehouse pieces with identity + expedition convenience stats (nulls only on OCR failure).
- Config is calibrated from live ADB screenshots before claiming collect works.
- Heroes collect and recommend remain unchanged.

## Known v1 OCR limits

- Enhancement (`+N`) and mastery (`Lv.N`) live on yellow icon badges; tesseract often misses them. When the level is glued into title OCR (`aer30 Judicator's…`) parsing works; otherwise fields may be null.
- Piece names sometimes OCR poorly (`TV RP` instead of a real title) — keep `raw_text` / detail screenshots for correction.
- Start with **Backpack → Gear** already open; the collector does not navigate there yet.

## Implementation order

1. Live ADB calibration → `config/gear.yaml` + reference screenshots under `artifacts/gear/calibration/`.
2. Model + parse + store + tests with fixtures.
3. Scrape/collect loop + CLI.
4. Device verification run (smoke: first row).
