# Grid Foundation: SQLite + Diamond UI + H3 Index Design

**Date:** 2026-07-31  
**Status:** Approved / implemented  
**Workspace:** `/Users/alexei/KS`  
**Foundation:** `artifacts/cartograph-grid300-5x5-badland-v9/` registered panorama + affine projection  
**Related:**  
- `docs/superpowers/specs/2026-07-31-diamond-digital-map-design.md`  
- `docs/superpowers/specs/2026-07-31-exact-object-registration-design.md`

## Goal

Treat the registered v9 mosaic as the authoritative **diamond grid foundation**: persist every covered tile and every detected entity in a capture-local SQLite database, export JSON/YAML/CSV as views, and show a trustworthy sparse diamond overlay with pins only for cities and alliance buildings. Prepare **H3 (default res 9)** as a secondary spatial index for resources and detail queries, without pretending Earth WGS84 matches KingShot geometry.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Placement authority | Existing exact-object registration + affine `world_to_pixel` matrix |
| Storage | Capture-local `{capture_dir}/cartograph.sqlite` (approach A) |
| File exports | `map.json`, `entities.yaml`, `entities.csv`, `registration.yaml` remain exports / views |
| UI pins | Cities + alliance buildings only: `city`, `mill`, `hq`, `banner`, `building`, `trap` |
| UI lattice | Sparse diamonds (step 2) + center marker on panorama |
| Full catalog | **All** kinds stored in SQLite (RSS, beasts, unknowns, …), even if UI hides them |
| Primary coords | Integer KingShot diamond tiles `(tile_x, tile_y)` + kingdom id |
| Secondary index | H3 cell ids (default **res 9** for resources/details; optional **res 7** on entities for coarser queries) |
| WGS84 | **Not** geographic ground truth. Used only if required as an H3 API carrier inside a reversible helper |
| Hex UI | Out of scope this slice (no hex overlay yet) |

## Coordinate authority

1. **Diamond game tiles** are the only gameplay / UI coordinate system.  
2. The affine projection maps diamond world ↔ panorama pixels.  
3. H3 indexes are **derived** and must always be regenerable from `(kingdom, tile_x, tile_y)` via a documented helper.  
4. If H3 and diamond disagree after a round-trip through the helper, **diamond wins**; H3 is rebuilt.

### Translation helper (required)

Provide a small, explicit module (e.g. `ks/cartograph/h3_index.py`) with a bidirectional API:

```text
game_tile_to_h3(kingdom, tile_x, tile_y, *, res) -> h3_index
h3_to_game_tile(kingdom, h3_index, *, crs) -> (tile_x, tile_y)   # nearest diamond tile
```

**CRS payload** (stored on each capture / kingdom embedding record):

- `crs_id` — stable name (e.g. `ks-local-v1`)  
- `origin_tile_x`, `origin_tile_y` — diamond origin for the embedding  
- `meters_per_tile` — local scale (instrumental, not survey truth)  
- `carrier` — `synthetic_wgs84` (or later a true local IJ scheme if we abandon lat/lng carriers)  
- `h3_detail_res` — default `9`  
- `h3_region_res` — optional `7`

**WGS84 caveat (binding):**

KingShot isometric diamonds are **not** Earth geography. Mapping tiles through synthetic lat/lng so the H3 library can run is an implementation detail. Callers must:

- never display synthetic lat/lng as real-world GPS;  
- always go **game → helper → H3** and **H3 → helper → game** for application logic;  
- treat helper round-trip error as a first-class metric (tile disagreement must be zero for integer tile centers under the chosen quantisation).

If synthetic WGS84 proves unstable for indexing, replace the carrier inside the helper without changing diamond columns or UI. Schema keeps H3 string/integer columns either way.

## SQLite schema (capture-local)

File: `{capture_dir}/cartograph.sqlite`

### `captures`

- `id` INTEGER PK  
- `kingdom` TEXT NOT NULL  
- `center_x`, `center_y` INTEGER NOT NULL  
- `matrix_json` TEXT NOT NULL — 2×2 world→pixel  
- `panorama_width`, `panorama_height` INTEGER  
- `registration_json` TEXT — metrics/graph summary  
- `crs_json` TEXT NOT NULL — H3 helper CRS payload above  
- `created_at` TEXT  

### `tiles`

- `tile_x`, `tile_y` INTEGER NOT NULL  
- `covered` INTEGER NOT NULL  
- `terrain` TEXT NOT NULL — keep `"unknown"` unless explicitly classified  
- `sampled_rgb_json` TEXT  
- `pixel_center_json`, `polygon_json` TEXT  
- `h3_res9` TEXT NOT NULL — indexed  
- PRIMARY KEY (`tile_x`, `tile_y`)

### `entities`

- `id` INTEGER PK  
- `kind`, `label`, `identity` TEXT  
- `level` INTEGER NULL  
- `tile_x`, `tile_y` INTEGER NOT NULL  
- `w`, `h` INTEGER NOT NULL  
- `world_x`, `world_y` REAL NULL  
- `confidence` REAL  
- `provenance` TEXT NOT NULL  
- `source_frames_json` TEXT  
- `coordinate_residual_px` REAL  
- `popup_path` TEXT  
- `h3_res9` TEXT NOT NULL — indexed (resources/details default)  
- `h3_res7` TEXT NULL — optional coarser index  
- `ui_pin` INTEGER NOT NULL — 1 iff kind is in the UI pin allow-list  

Indexes: `(h3_res9)`, `(h3_res7)`, `(kind)`, `(ui_pin)`, `(tile_x, tile_y)`.

## Overlay / HTML

- Reuse affine diamond overlay on the unrotated panorama.  
- Lattice: every **2nd** tile in both axes among covered tiles (configurable).  
- Pins: entities with `ui_pin = 1` only.  
- Optional QA PNG: panorama + lattice + pins for offline review.

## Digitization behaviour

- Run full entity detection (OCR + visual) into SQLite — **no kind dropped**.  
- Improve OCR path so cities / alliance buildings become named `ocr_projected` rows (UI pins).  
- Uncertain kinds remain `unknown` in DB rather than inventing labels.  
- After write: export views from SQLite so file and DB cannot diverge in one pipeline run.

## Pipeline integration

Extend `register_and_digitize_capture` (or a thin successor) to:

1. Register + fail-closed stitch (existing).  
2. Digitize all entities.  
3. Build covered tile records from the mosaic projection.  
4. Compute H3 indexes via the helper using capture CRS.  
5. Replace/write `cartograph.sqlite`.  
6. Export JSON/YAML/CSV + filtered `map.html`.

## Error handling

- Fail closed if registration thresholds fail (unchanged).  
- Fail closed if CRS payload missing/invalid when writing H3 columns.  
- Fail closed if `game_tile → h3 → game_tile` does not recover the same integer tile for a sample of written tiles.  
- Do not invent terrain classes from colour.

## Verification

- Round-trip helper tests for a grid of tiles around the capture center.  
- SQLite contains ≥ covered tile count from `map.json` and all entity kinds produced by digitization.  
- UI pin count equals entities whose kind is in the allow-list.  
- Sparse overlay diamonds lie on affine tile centres (spot-check known Badland / mill coords on v9).  
- Rebuild of v9 produces `cartograph.sqlite` + exports without diverging entity counts between DB and `entities.yaml`.

## Out of scope

- Project-global multi-capture database.  
- Rendering H3 hexes on the panorama.  
- Claiming synthetic lat/lng is real GPS.  
- Live ADB capture changes beyond writing the new DB/export path for offline rebuilds.
