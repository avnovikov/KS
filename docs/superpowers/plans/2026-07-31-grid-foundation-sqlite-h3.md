# Grid Foundation SQLite + H3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or execute directly with TDD.

**Goal:** Persist v9-style captures to capture-local SQLite with diamond tiles + full entities, H3 secondary indexes via a reversible helper, and a sparse diamond grid overlay with city/alliance pins only.

**Tech Stack:** Python 3.12+, sqlite3, h3, pytest, existing cartograph mosaic/render/pipeline.

## File map

| File | Responsibility |
|------|----------------|
| `ks/cartograph/h3_index.py` | CRS + `game_tile_to_h3` / `h3_to_game_tile` |
| `ks/cartograph/store.py` | SQLite schema, write/read capture |
| `ks/cartograph/render_map.py` | Sparse lattice step + UI pin filter |
| `ks/cartograph/pipeline.py` | Wire DB + filtered overlay after digitize |
| `pyproject.toml` | add `h3` dependency |
| Tests | `test_cartograph_h3_index.py`, `test_cartograph_store.py`, render/pipeline updates |

## Tasks

### Task 1: H3 translation helper
- Failing round-trip tests around an origin
- Implement `KingdomCrs`, `game_tile_to_h3`, `h3_to_game_tile`, `assert_round_trip_sample`
- Synthetic WGS84 carrier only; never expose as GPS

### Task 2: SQLite store
- Failing tests for schema + write/read tiles/entities/h3/ui_pin
- Implement `write_capture_db` / `open_capture_db`

### Task 3: Sparse grid overlay + UI pins
- Failing tests: lattice step 2; pins only allow-list kinds
- Update `render_iso_overlay_unrotated` / `write_map_bundle`

### Task 4: Pipeline + v9 rebuild
- After digitize: write sqlite, export views, filtered map.html
- Rebuild v9; verify DB tile/entity counts and overlay

Do not commit unless asked.
