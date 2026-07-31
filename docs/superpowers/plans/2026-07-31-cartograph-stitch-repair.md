# Cartograph Stitch Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.  
> **Findings:** `docs/superpowers/specs/2026-07-31-cartograph-stitch-review.md`

**Goal:** Fix bad panorama merges for isometric World-map grid captures: world-affine placement, hardened step calibration, viewport audit/dedupe, and OCR-gated swipe verification — then offline-restitch `artifacts/cartograph-grid17x17/` without live recapture.

**Architecture:** World OCR viewports (after outlier/dup filter) are the placement authority. Fit a 2×2 `world_to_pixel` matrix; paste bands at `M @ (vp - center)`. Cell-index lattice and landmark BFS become optional refine only after a valid diamond basis. Capture must refuse saves when OCR tile delta is insufficient.

**Tech Stack:** Python 3.13, NumPy, OpenCV, pytest, YAML.

## Global Constraints

- Prefer offline repair of existing `artifacts/cartograph-grid17x17/` frames; do not require live ADB recapture.
- Exact/diamond geometry: publish `world_to_pixel_matrix` on every successful mosaic.
- Fail closed on unreadable World-map coordinate bars (existing ADB-first rule).
- Land coord-gate from stash `wip swipe-coord-gate` conceptually; re-implement cleanly if stash conflicts.
- Keep changes focused under `ks/cartograph/` + tests; update this plan checkboxes as work completes.

---

### Task 1: Viewport audit + keep-list

**Files:**
- Create or extend: helper in `ks/cartograph/mosaic.py` or `ks/cartograph/viewport.py` (e.g. `audit_grid_frames` / `filter_viewport_frames` used by grid path)
- Test: `tests/test_cartograph_mosaic.py` (or new `tests/test_cartograph_viewport_audit.py`)
- Artifact out: `artifacts/cartograph-grid17x17/keep_frames.yaml` (optional CLI/script)

- [x] Drop OCR outliers vs median / robust linear residual.
- [x] Drop exact and near-duplicate viewports (keep one representative).
- [x] Tests for synthetic dup/outlier cases.

### Task 2: World-affine restitch path

**Files:**
- Modify: `ks/cartograph/mosaic.py` (`stitch_viewport_mosaic`, `stitch_grid_lattice`)
- Modify: `ks/cartograph/project.py` if fitting helpers belong there
- Test: `tests/test_cartograph_mosaic.py`

- [x] Fit 2×2 `M` from kept `(world, pixel)` or place at `M @ (vp - center)` with calibrated `M`.
- [x] Default folder restitch uses world placement (not cell lattice alone).
- [x] Always set `MosaicResult.world_to_pixel_matrix`.
- [ ] Offline regenerate `panorama.png` + `map.html` for `artifacts/cartograph-grid17x17/`.

**Restitch note (offline):** after Tasks 1–2 land, regenerate from an existing capture folder with:

```bash
source .venv/bin/activate
python -m ks.cartograph.cli map --capture-dir artifacts/cartograph-grid17x17
```

(`stitch_viewport_mosaic` now audits + world-affine places `g_*` frames and publishes `world_to_pixel_matrix`.)

### Task 3: Harden `calibrate_grid_pixel_steps`

**Files:**
- Modify: `ks/cartograph/mosaic.py`
- Test: `tests/test_cartograph_mosaic.py` / calibration tests

- [ ] Diamond-aware default seed when `e_len < 6` (do not collapse East to horizontal).
- [ ] Gate or remove unconditional `ps[1]` flip; expand NCC search around diagonal seeds.
- [ ] Regression test: median E ≈ `(4,-4)` must not yield `pe_y ≈ 0`.

### Task 4: OCR coord-gated swipe + save

**Files:**
- Modify: `ks/cartograph/mosaic.py` (`swipe_camera_verified`, `capture_grid`)
- Modify: `ks/cartograph/live_capture.py` if `camera_moved` API changes
- Test: `tests/test_live_capture_safe_actions.py` / mosaic capture tests

- [ ] Require OCR tile delta ≥ threshold before accepting a swipe.
- [ ] Refuse saving a frame whose viewport equals previous saved viewport.
- [ ] Tests prove pixel-only flicker is rejected.

### Task 5: Mask / feather polish (after geometry)

**Files:**
- Modify: `ks/cartograph/mask.py`, `mosaic._paste_band_structure_aware` (optional feather)

- [ ] Only after Tasks 1–3 produce a coherent panorama.
- [ ] Reduce repeated HUD on rim; optional soft blend in overlaps.

### Task 6: Verification

- [ ] Focused pytest green for touched modules.
- [ ] Visual check: restitched panorama continuous; no HUD stair columns.
- [ ] HotspotTriage re-scan `ks/cartograph/**` (expect mosaic calibration/placement risk down if split).
- [ ] Update findings doc status if fixes land.

## Out of scope

- Full live 17×17 recapture (blocked without device network / user request).
- Replacing registration solver (already correct path; wire CLI to it later if needed).
