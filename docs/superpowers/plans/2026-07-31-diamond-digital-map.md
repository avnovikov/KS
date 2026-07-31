# Diamond Digital Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a correctly projected diamond-tile panorama, interactive overlay, and machine-readable map from the 25-frame capture.

**Architecture:** Add one validated affine projection contract and carry it in `MosaicResult`. Rendering and digital export consume that contract instead of reconstructing rectangular scales or a second isometric transform.

**Tech Stack:** Python 3.13, NumPy, OpenCV, pytest, SVG/HTML, JSON.

## Global Constraints

- Exact clicked or viewport coordinates are the primary geometry source.
- A world tile has two diagonal screen basis vectors.
- Popup screenshots are never used as clean mosaic frames.
- Legacy mosaics without affine metadata retain their current behavior.
- New behavior is implemented test-first.

---

### Task 1: Affine projection contract

**Files:**
- Modify: `ks/cartograph/project.py`
- Test: `tests/test_cartograph_project.py`

**Interfaces:**
- Produces: `AffineProjection(center, pixel_origin, matrix)`
- Produces: `AffineProjection.pixel_from_world()`, `world_from_pixel()`,
  `tile_polygon()`, and `world_bounds_for_image()`

- [ ] Add failing tests for a diamond matrix, inverse round trip, projected
  tile corners, and four-corner image bounds.
- [ ] Run `pytest tests/test_cartograph_project.py -v`; confirm the new API is
  missing.
- [ ] Implement the frozen value object with explicit shape, finite-value, and
  invertibility validation.
- [ ] Run the focused tests and preserve the existing functional API.

### Task 2: Carry affine geometry through mosaics

**Files:**
- Modify: `ks/cartograph/mosaic.py`
- Test: `tests/test_cartograph_mosaic.py`

**Interfaces:**
- Consumes: `AffineProjection`
- Produces: optional `MosaicResult.world_to_pixel_matrix`
- Produces: `mosaic_projection()` and `panorama_world_bounds()`

- [ ] Add failing tests proving `world_to_panorama()` follows both diagonal
  basis vectors and bounds inverse-project all image corners.
- [ ] Run the focused tests and confirm rectangular placement fails them.
- [ ] Add optional affine metadata without breaking existing constructors.
- [ ] Route coordinate conversion and bounds through `AffineProjection`,
  falling back to the legacy diagonal scalar matrix.
- [ ] Run `pytest tests/test_cartograph_mosaic.py -v`.

### Task 3: Diamond overlay and canonical JSON map

**Files:**
- Modify: `ks/cartograph/render_map.py`
- Test: `tests/test_cartograph_render_map.py`

**Interfaces:**
- Consumes: `mosaic_projection()` and `panorama_world_bounds()`
- Produces: `render_digital_map_json()`
- Writes: `map.json`

- [ ] Add failing tests that assert projected diamond polygons use the mosaic
  matrix and `map.json` contains covered tiles, projection metadata, sampled
  color, and entities.
- [ ] Run the focused test and verify failure for missing digital export.
- [ ] Replace the synthetic overlay shear with projection of all four world
  corners.
- [ ] Generate bounded covered tiles and serialize stable, indented JSON.
- [ ] Place the diamond overlay directly above the panorama in `map.html` and
  link `map.json`.
- [ ] Run `pytest tests/test_cartograph_render_map.py -v`.

### Task 4: Rebuild the 25-frame deliverable

**Files:**
- Create: `artifacts/cartograph-grid300-5x5-badland-v9/map.json`
- Modify generated: `artifacts/cartograph-grid300-5x5-badland-v9/map.html`
- Modify generated: `artifacts/cartograph-grid300-5x5-badland-v9/panorama.png`

**Interfaces:**
- Consumes: `calibration.yaml`, 25 clean frames, and existing entity inputs
- Produces: the morning review bundle

- [ ] Load the calibrated 2×2 diamond matrix and corrected per-frame viewport
  coordinates.
- [ ] Reconstruct a `MosaicResult` with affine metadata and write the complete
  map bundle.
- [ ] Verify 25 clean source frames, no popup detections, a non-singular
  projection, and JSON tile centers inside the panorama.

### Task 5: Regression verification

**Files:**
- Test only

- [ ] Run `pytest tests/test_cartograph_project.py tests/test_cartograph_calibration.py tests/test_cartograph_mosaic.py tests/test_cartograph_render_map.py -v`.
- [ ] Run repository lint diagnostics for edited Python files.
- [ ] Inspect `panorama.png`, `map.html`, and representative `map.json` tiles.
- [ ] Report any pre-existing failures separately from introduced failures.
