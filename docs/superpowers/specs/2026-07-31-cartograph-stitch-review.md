# Cartograph Stitch / Merge Review (2026-07-31)

> **Status:** findings from PR-style review + HotspotTriage on `ks/cartograph/**` after partial 17×17 capture.  
> **Artifact:** `artifacts/cartograph-grid17x17/` (`panorama.png`, `map.html`, `entities.yaml`).  
> **Constraint:** live recapture may be unavailable (no device internet); prefer **offline** repair first.  
> **Main tip reviewed:** `cd47272` (digitization + one-tile lattice merged).

## Symptom

`panorama.png` merge looks badly wrong: staircase edges, torn seams, ghosted cities/beasts, repeated HUD chips (`3/4`), fragmented water/fog blocks. Digital entity pins around center `(696,788)` are more plausible than the mosaic geometry.

## HotspotTriage summary

Scoped analyze: `filter=ks/cartograph/**`, `since=2026-07-01`, head `cd47272`.

| Metric | Value |
|--------|-------|
| Blocks | 253 |
| Critical risk | 11 |
| High risk | 63 |
| Mean score | 0.54 |
| Max score / cc | `mosaic.stitch_grid_lattice` (score ~0.90, cyclomatic 41) |

Top critical/high functions (triage focus for fixes):

1. `mosaic.stitch_grid_lattice`
2. `mosaic.stitch_viewport_mosaic`
3. `mosaic.calibrate_grid_pixel_steps`
4. `mosaic.place_grid_by_landmarks` / `_place_edge_anchored_grid`
5. `render_map.render_iso_overlay_unrotated` / `render_html`
6. `registration.*`, `live_capture.*` (churn + capture gate)

## What works

- `AffineProjection` (`project.py`) — solid world↔pixel 2×2 contract.
- Exact-object registration path (`pipeline.register_and_digitize_capture` → `registration.solve_frame_translations` → lattice with `frame_offsets` + `world_to_pixel_matrix`) is the **correct** architecture.
- Structure-aware paste (`_paste_band_structure_aware`) prefers buildings over grass.
- ADB-first capture discipline mostly present (World-map checks, popup dismiss, fail-closed on unreadable coords in `_save`).
- Stash `wip swipe-coord-gate` already implements OCR tile-delta gate + duplicate viewport refusal (not on `main`).

## Critical issues

### 1. Default lattice East step collapses toward axis-aligned

**Where:** `mosaic.calibrate_grid_pixel_steps`

When median neighbor tile length `e_len < 6`, East step `pe` stays ~(overlap × band_w, 0). On the 17×17 set median E ≈ `(4, -4)` → `e_len ≈ 5.66`, so:

- no refine: `pe ≈ (415.8, 0)`
- with refine: `pe ≈ (285, 57.5)` — still nearly horizontal

A clean 5×5 subset wants isometric ~`(224, -243)`. CLI restitch uses `stitch_viewport_mosaic` → `stitch_grid_lattice` **without** `frame_offsets`, so bad `pe/ps` drives placement → staircase panorama.

### 2. Grid path places by screen cell, not world coords

**Where:** landmark/lattice branch of `stitch_grid_lattice`

Positions are `ex*pe + ey*ps` (or landmark BFS). OCR viewports are used mainly for step calibration, not paste location. Stuck / near-duplicate frames still get pasted far from where their pixels belong → ghosts and torn seams.

### 3. Pixel-only camera verification accepted bad cells

**Where:** `mosaic.swipe_camera_verified`, `live_capture.camera_moved`

Main accepts phaseCorrelate / mean-delta flicker as “moved”. Capture produced exact/near-duplicate viewports on distant cells (e..g. `(698,816)` on multiple cells). Coord-gated fix lives in git stash `wip swipe-coord-gate`, not on `main`.

### 4. No viewport outlier filter on grid stitch

**Where:** `filter_viewport_frames` only on non-grid branch of `stitch_viewport_mosaic`

`stitch_grid_lattice` keeps every `g_*` cell, including OCR bombs (e.g. `g_-1_-1 → (1696,799)` likely `696` misread) that poison E-step extremes.

### 5. Default mosaic often publishes no diamond matrix

**Where:** `stitch_grid_lattice` leaves `world_to_pixel_matrix=None` unless calibration/`frame_offsets` path

`mosaic_projection` falls back to diagonal `((scale_x,0),(0,scale_y))`. Footprints on `map.html` then use legacy fake diamond bases in `render_map._iso_diamond_on_panorama`.

## Important issues

- `ps[1]` sign coercion in `calibrate_grid_pixel_steps` hard-codes “south = image-down”; coupled with bad `pe` locks a sheared rectangular lattice onto isometric motion.
- NCC refine radius (`_refine_steps_ncc`, radius≈220) may miss true diamond offset from an axis-aligned seed.
- Landmark BFS is first-wins; drift accumulates; edge-anchored fill lerps error across the middle.
- Hard max-weight overwrite (no feather) → hard seams / lighting checkerboard.
- Mask incomplete for periphery UI → repeated back/UI chips along panorama rim.
- CLI restitch path does not use `register_and_digitize_capture` for this artifact.
- `by_cell[cell] = f` last-write-wins with no viewport uniqueness when loading a folder.

## Minor

- Magic constants: `e_len >= 6`, overlap `0.55`, NCC radii, tile-scale guesses.
- `capture_grid` resume/progress only in stash.
- ~45% fill pixels amplify sparse/holey look.
- Docstring vs behavior: “never accept duplicate cell” but only checks pixels.

## Root-cause ranking (visual merge)

1. **Wrong lattice basis** (axis-aligned / semi-horizontal `pe`) on isometric swipes.
2. **Near-duplicate / mislabeled viewports** placed on a regular cell lattice.
3. **OCR outliers** poisoning geometry / calibration.
4. **Missing `world_to_pixel_matrix`** → wrong digital overlay (secondary to panorama).
5. **UI mask / hard paste seams** (polish after geometry).

## Offline fix order (no live recapture)

1. **Audit frames** — OCR all `g_*.png` / center; drop outliers (`|Δ|` from median), exact/near-dup viewports, high residual vs robust linear fit. Write keep-list YAML under the artifact dir.
2. **Restitch by world affine** — Fit 2×2 `pixel = M @ (world - center)`; place each band at `M @ (vp - center)`. Do **not** use landmark/cell lattice for repair. Set `MosaicResult.world_to_pixel_matrix = M`. Republish `panorama.png` + `map.html`.
3. **Harden `calibrate_grid_pixel_steps`** — diamond-aware default seed; fix/remove `e_len>=6` gate; expand NCC around diagonal seeds; gate `ps[1]` flip on measured motion.
4. **Land coord-gate on main** (stash `wip swipe-coord-gate`) — OCR `min_tile_delta`, refuse `vp == prev_vp` on save. Prevents recurrence; does not fix existing PNGs.
5. **Tighten mask + optional feathered blend** only after geometry is correct.

## Code fix acceptance criteria

- [ ] Unit/integration tests covering diamond E-step calibration when median tile Δ &lt; 6.
- [ ] Grid stitch path filters OCR outliers / duplicate viewports (or world-affine path is the default for folder restitch).
- [ ] Restitched `artifacts/cartograph-grid17x17/panorama.png` shows continuous terrain (no HUD stair columns; no obvious ghost cities at lattice offsets).
- [ ] `MosaicResult.world_to_pixel_matrix` published; `map.html` footprints track mosaic.
- [ ] `swipe_camera_verified` requires OCR tile delta (tests prove pixel-only flicker rejected).
- [ ] Focused pytest: mosaic calibration, viewport filter, camera verify, render projection.

## Related docs / artifacts

- **Authority lock:** `docs/superpowers/specs/2026-07-31-cartograph-registration-authority.md`
- Plan: `docs/superpowers/plans/2026-07-31-exact-object-registration.md`
- Specs: diamond digital map / object digitization under `docs/superpowers/specs/`
- Good reference mosaic: `artifacts/cartograph-grid300-5x5-badland-v9/`
- Broken set: `artifacts/cartograph-grid17x17/`
- Local stash (coord gate): `stash@{0}: wip swipe-coord-gate`

## Hotspot triage note for agents

Re-run after fixes:

```text
HotspotTriage analyze target=<repo> filter=ks/cartograph/** include_summary=true
```

Expect lower score / complexity on `stitch_grid_lattice` and `calibrate_grid_pixel_steps` if logic is split (audit → affine place → optional landmark refine).
