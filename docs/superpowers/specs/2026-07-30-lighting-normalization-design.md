# Lighting normalization — design

**Date:** 2026-07-30  
**Status:** Implemented — accepted for production (night assumed OK in live use)  
**Related:** `ks/cartograph/lighting.py`, `ks/cartograph/mosaic.py`, live capture artifacts

## Problem

KingShot map screenshots change color with in-game time of day: night grass is darker and bluer; noon is brighter and yellower. When cartograph stitches multiple captures into a panorama, raw bands produce visible day|night seams and degrade NCC overlap matching.

Current `normalize_band_lighting()` rescales global HSV Value and Saturation toward fixed targets and nudges grass hue toward 55°. This helps but leaves measurable color gaps — visible in `artifacts/cartograph-live/lighting-preview.png` and `panorama-preview.png`.

## Goal

Every captured map band should look like the same **mid-day reference** regardless of when it was taken, so:

1. Mosaic paste produces no lighting seams.
2. NCC / structure matching is stable across captures.
3. Normalization runs at capture/stitch time with no manual per-frame tuning.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Reference anchor | **A — today's live capture.** Canonical band: `artifacts/cartograph-live/band-g_2_0.png` (brightest/greenest grass among live bands). Copied to `assets/reference/cartograph/lighting-reference.png` at implementation time. |
| Algorithm | **Log-chrominance shift** (Barron ICCV 2015) on grass-masked pixels, then brightness/saturation anchor (existing HSV targets). |
| Scope | Map bands only (post mask+crop). UI chrome excluded by existing mask pipeline. |
| Dependencies | No new packages. OpenCV + NumPy only (already in `pyproject.toml`). |
| Not in v1 | Histogram matching (scikit-image), learned CCC model, per-session auto-reference |

## Algorithm

### Step 1 — Grass mask

On each band (reference and source), select pixels where:

- HSV hue ∈ [30, 95]
- Saturation > 25
- Value > 20

Fallback to all non-black pixels if grass count < 500.

### Step 2 — Log-chrominance shift

Per Barron, illumination changes approximate a **translation** in log-chrominance space:

```text
u = log(G / R)
v = log(G / B)
```

Estimate shift from source → reference using **median** (robust to buildings, shields, labels):

```text
du = median(ref_u[grass] - src_u[grass])
dv = median(ref_v[grass] - src_v[grass])
```

Apply to all pixels:

```text
u' = u + du
v' = v + dv
```

Reconstruct BGR from `(u', v')` with green channel anchored:

```text
G' = G * exp(du)          # uniform green scale from du
R' = G' / exp(u')
B' = G' / exp(v')
```

Clip to [0, 255].

### Step 3 — Brightness / saturation anchor (keep existing)

After log-chrom shift, apply current HSV rescale:

- Mean Value → 145 (on non-fill pixels, V > 12)
- Mean Saturation → 85
- Grass hue blend: `h = 0.55*h + 0.45*55` on grass mask

This preserves the proven mid-day look while fixing per-channel color cast that global V/S scaling misses.

### Step 4 — Match gray (unchanged)

`band_match_gray()` continues to use Laplacian edges on the normalized band for NCC. Structure, not grass tone.

## Module changes

| File | Change |
|------|--------|
| `ks/cartograph/lighting.py` | Add `load_lighting_reference()`, `estimate_log_chrom_shift()`, `apply_log_chrom_shift()`. Extend `normalize_band_lighting()` to run log-chrom shift first when reference is available. |
| `assets/reference/cartograph/lighting-reference.png` | Copy of `band-g_2_0.png` (756×1075 cropped map band). |
| `config/params.yaml` | Add `cartograph.lighting_reference` path (default above). |
| `tests/test_cartograph_lighting.py` | Tests for shift estimation, reconstruction, day/night convergence. |
| `scripts/lighting_preview.py` (new) | Regenerate 4-panel before/after preview from live capture bands. |

## Data flow

```text
screencap → mask+crop → band
  → log_chrom_shift(band, reference)
  → hsv_anchor(band)          # existing targets V=145, S=85
  → paste / band_match_gray()
```

Reference loaded once per mosaic run (or CLI session), not per pixel.

## Success criteria

- [x] Post-normalize grass `(V, S, H)` spread across live bands reduced vs raw (preview + metrics).
- [x] Log-chrom `(u, v)` gap tightened (blue cast spread ~33% of raw on test bands).
- [x] `test_cartograph_lighting.py` passes (8 tests).
- [x] Panorama rebuild shows reduced lighting seams (`panorama-lighting-compare.png`).
- [x] **Night:** assumed OK in production — no dedicated night test matrix for v1.

## Risks

| Risk | Mitigation |
|------|------------|
| Reference itself is night/dusk | Scoring picks brightest/greenest band; document how to re-pick reference. |
| Grass mask includes shields (orange) | Median is robust; optionally exclude high-sat non-green (H outside 30–95 already handled). |
| Different zoom/resolution vs reference | Resize source to reference size before shift estimate; apply shift on native band. |
| Region change (not bear-trap) | Reference is session-local; re-capture reference when moving to a new area. |
| Night captures untested at scale | **Accepted:** operator assumes log-chrom + HSV anchor is sufficient for night; no further night-specific tuning in v1. Re-pick reference if seams appear in live night sessions. |

## Alternatives considered

| Approach | Why not primary |
|----------|-----------------|
| Histogram matching to reference | Stronger but distorts building colors; adds scikit-image dep. |
| Gray World (OpenCV xphoto) | Biased by grass-dominated scenes; needs opencv-contrib. |
| HSV-only (current) | Insufficient for blue night cast; kept as step 3 anchor only. |
