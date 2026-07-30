# Bear Trap map capture — findings (for OCR resume)

**Date:** 2026-07-30  
**State:** #2339 [UTD]  
**Status:** Grid/stitch calibration paused; ready to OCR structures from screens  
**Design:** `docs/superpowers/specs/2026-07-30-bear-trap-placement-design.md`

This file is the handoff. Machine-readable twins live next to it (YAML/JSON listed below).  
**Lessons for a future OCR module:** see § [Lessons learned](#lessons-learned--future-ocr-module) (also `ocr-calibration.yaml` → `lessons_learned`).

---

## Goal (when we resume)

1. OCR / digitize **permanent structures** on the map (skip animals + clearable small farms).
2. Refresh `blockers.yaml`.
3. Run `scripts/bear_trap_map.py` and propose a **new trap** (Trap 2 fixed).

---

## Locked placement rules

| Item | Value |
|------|--------|
| Trap 2 (fixed) | **698, 816** |
| City | **2×2** |
| Trap / pitfall | **~3×3** |
| Mills / banner | **1×1** |
| New-trap sweep | D ≈ 5–12, prefer E/W, preferred D ≈ 7 |
| DO NOT TELEPORT zone | ignore for placement |

Config: `config/bear_trap.yaml`  
Partial blockers (popup-confirmed): `assets/reference/bear-trap/blockers.yaml`

---

## Screenshot sources

| Batch | Album / path | Notes |
|-------|----------------|-------|
| batch3 (primary) | `blockers-shots/batch3/` · viewport YAML below | 12 shots, same zoom, native **1080×2424** |
| Cropped (OCR/stitch input) | `blockers-shots/batch3-cropped/` | UI masked + cropped → **1080×1667** |
| Panorama | `panorama-stitching-batch3.png` | **3874×3064**, all 12 shots |
| Grid overlay (WIP) | `panorama-iso-grid.png` | zigzag-locked; not required for OCR |
| Photos album | https://photos.app.goo.gl/3vU9naPvTLaNgkPq5 | batch3 source |

---

## UI mask + crop (native 1080×2424)

Calibrated from user FIXED reference on b3-07. Code: `scripts/stitch_batch3_opencv.py`.

```text
CROP_TOP    = 0.1787   → drop top bar
CROP_BOTTOM = 0.8662   → drop bottom nav
CROP_LEFT   = 0.0
CROP_RIGHT  = 1.0
→ cropped size 1080 × 1667
```

Mask rects (fractions of native W×H), painted black before crop:

| Region | (x0,y0)–(x1,y1) |
|--------|------------------|
| Top status / resources / teleport | (0, 0)–(1, 0.1787) |
| Left marching panel | (0, 0.1787)–(0.3355, 0.2842) |
| Left edge tab | (0, 0.4463)–(0.0504, 0.5137) |
| Right event icons | (0.8772, 0.1787)–(1, 0.4443) |
| Bottom-left PiP | (0, 0.6963)–(0.2478, 0.8662) |
| Bottom-right compass/mail | (0.8728, 0.7783)–(1, 0.8662) |
| Bottom nav | (0, 0.8662)–(1, 1) |

Also saved in: `assets/reference/bear-trap/ocr-calibration.yaml`

---

## Viewport centers (search bar coords)

File: `viewport-coords-batch3.yaml`

| Shot | X | Y |
|------|---|---|
| b3-01 | 697 | 819 |
| b3-02 | 693 | 822 |
| b3-03 | 690 | 825 |
| b3-04 | 698 | 833 |
| b3-05 | 700 | 829 |
| b3-06 | 703 | 825 |
| b3-07 | 707 | 822 |
| b3-08 | 711 | 818 |
| b3-09 | 703 | 812 |
| b3-10 | 698 | 815 |
| b3-11 | 694 | 819 |
| b3-12 | 689 | 821 |

**Spatial notes (operator):** b3-02 and b3-03 are **left (west)** of b3-01; b3-04 and b3-05 sit **above-left** along territory lines (not south of the trap).

---

## Stitch placements (ORB pairwise)

Script: `scripts/stitch_batch3_orb.py`  
Origin: **b3-01 at (0,0)** = top-left of cropped image.  
Canvas origin shift ≈ **(minx, miny) = (−1326, −1090)**  
Cropped image size: **1080 × 1667**  
Shot center on panorama ≈ `(ox - minx + 540, oy - miny + 833.5)`

| Shot | ox | oy |
|------|----|----|
| b3-01 | 0 | 0 |
| b3-02 | −687 | −26 |
| b3-03 | −1303 | −9 |
| b3-04 | −1326 | −1090 |
| b3-05 | −784 | −942 |
| b3-06 | 13 | −921 |
| b3-07 | 610 | −924 |
| b3-08 | 1469 | −983 |
| b3-09 | 1176 | 16 |
| b3-10 | 469 | 92 |
| b3-11 | −257 | 154 |
| b3-12 | −983 | 306 |

Do **not** link 01→04 for stitching (pulls south). Use 02/03 ↔ 04/05 along territory border.

---

## World ↔ pixel (viewport fit)

Least-squares from stitch Δpos vs viewport Δworld:

```text
pixel_delta ≈ MAT @ world_delta

MAT ≈ [[ 95.71, -99.50 ],
       [-67.69, -68.09 ]]

|col0| (ΔX=1) ≈ 117.2 px @ −35.3°
|col1| (ΔY=1) ≈ 120.6 px @ −145.6°
normal step ΔY≈113 px, ΔX≈110 px
```

**Caveat:** residual when mapping Trap2→HQ (~705,823) was still large (~hundreds of px) on earlier trials — good for approximate OCR boxes, refine after labeling a few anchors on the panorama.

Inverse: `world_delta ≈ inv(MAT) @ pixel_delta`.

---

## Grid / blue borders (paused — optional for OCR)

- Thick alliance borders are **not** 45°; they run ≈ **±35°** (aligned with world X/Y screen axes).
- One tile measured from **top-left blue zigzag L-corner**: edge ≈ **110×109 px**, step ≈ **106×107 px**.
- Calibration snapshot: `iso-grid-cal.json` (method `zigzag_one_square_is_grid`).
- Overlay script: `scripts/overlay_iso_grid.py` — **phase still imperfect vs thick stroke midlines**; do not block OCR on this.
- Prefer OCR on **individual cropped shots** (labels sharper) and/or panorama with viewport+MAT pins.

---

## Confirmed same-world objects (stitch / OCR anchors)

Full detail: `batch3-element-inventory.yaml`

| Object | World (approx) | Same in shots |
|--------|----------------|---------------|
| Hunting Trap 2 | 698, 816 | 01, 10 (+ beam/moon in 06, 07) |
| Plains HQ | ~705, 823 | 06, 07 |
| Alliance Iron Mine | ~704, 830 | **06, 07, 08** |
| Woodmill near trap | ~702, 815 | **07, 09, 10** |
| Woodmill near HQ | ~699, 823 | **01, 06, 11** |
| Alliance Mill | ~695, 834 | 01, 04, 11 |
| City ACE 25 | ~696, 814 | 01, 10, 11 |
| City Pinky 22 | ~708, 822 | 07 |
| City Hazy 20 | ~706, 821 | 07 (+ partial 06) |
| Lv6 mill/crane | — | **11, 12** (+ likely 02) |
| Moose + woodmill | — | **09, 10** |
| Iron mine | — | **07, 08** (with 06) |
| Lv5 + Lv7 harvest | — | **03, 04** |

**Banners:** many distinct — do **not** use as primary stitch/OCR merge keys.

**OCR should skip:** animals/mobs, clearable small farms. Keep: cities, alliance buildings, RSS nodes that block seats, terrain rocks if permanent.

---

## Already digitized (popup coords)

From `blockers.yaml` (batch2 popups; refine with batch3 OCR):

- alliance_banner 695,820 (1×1)
- woodmill_near_trap 702,815 (1×1)
- woodmill_north 699,823 (1×1)
- iron_mine 704,830 (1×1)
- alliance_mill 695,834 (1×1)
- plains_hq 705,823 (5×5 TBD)
- cities ACE / Hazy / Pinky (2×2)

---

## Scripts (venv: `source scripts/env.sh`)

| Script | Role |
|--------|------|
| `scripts/stitch_batch3_opencv.py` | Mask+crop batch3 → `batch3-cropped/` |
| `scripts/stitch_batch3_orb.py` | ORB stitch → panorama |
| `scripts/overlay_iso_grid.py` | Optional grid overlay |
| `scripts/bear_trap_map.py` | Placement sweep → HTML/CSV |
| `ks/placement/viewport_ocr.py` | Existing viewport OCR helper (search-bar coords) |

---

## Suggested OCR workflow (next session)

1. Run OCR on **`batch3-cropped/*.png`** (cleaner than full native UI).
2. For each label hit, convert shot-local pixel → world using:
   - viewport center of that shot
   - MAT (or refine with 2–3 known popup anchors in that shot)
3. Deduplicate via `batch3-element-inventory.yaml` match groups.
4. Merge into `blockers.yaml` (permanent only).
5. Re-run `bear_trap_map.py` with Trap 2 fixed.

---

## Artifact index

| Path | What |
|------|------|
| `ocr-calibration.yaml` | **This handoff, machine-readable** (mask, stitch, MAT, viewports) |
| `viewport-coords-batch3.yaml` | Per-shot search-bar coords |
| `batch3-element-inventory.yaml` | Same-object groups |
| `blockers.yaml` | Digitized blockers so far |
| `iso-grid-cal.json` | Zigzag tile measurement (optional) |
| `panorama-stitching-batch3.png` | Stitched map |
| `panorama-iso-grid.png` | Grid overlay (WIP) |
| `blockers-shots/batch3-cropped/` | Best images for OCR |

---

## Lessons learned — future OCR module

These are design constraints for a reusable KingShot map OCR / digitizer (not only this bear-trap batch).

### 1. Pipeline order (do not skip)

```text
capture (same zoom)
  → mask UI chrome (fractional rects, per resolution)
  → crop to map band
  → read viewport center (search bar X/Y) per shot
  → OCR labels on cropped shots (not raw UI, not only panorama)
  → map label pixels → world via viewport + pixel↔world model
  → dedupe same-world objects across shots
  → emit blockers / structures YAML
```

Panorama is for **human review and coarse layout**, not the primary OCR surface (stitch blur, seams, doubled labels).

### 2. UI mask is mandatory

- Floating panels (march list, events, PiP, nav) destroy OCR and stitch matches.
- Calibrate mask once from a **user-fixed reference** frame; store as **fractions of W×H**, not absolute pixels.
- Keep mask config next to the shot set (`ocr-calibration.yaml` / stitch script constants).
- Viewport OCR uses a *different* crop (search bar) — that region must stay readable on the **native** shot before map crop, or be read before masking.

### 3. Viewport pin is the spatial key

- Every shot needs `(vx, vy)` from the search bar (`#2339 X:… Y:…`).
- Prefer dedicated viewport OCR (`ks/placement/viewport_ocr.py`) + **manual YAML fallback** when digits flip (common).
- Validate against a local range for the site; reject outliers.
- Shot-local pixel → world: treat viewport as the crop center in world space, then apply `MAT` (or a refined local fit from 2–3 popup anchors in that shot).

### 4. Same zoom is a hard requirement

- Mixed zoom breaks MAT, stitch, and city-ruler scaling.
- Record zoom implicitly by keeping a known **2×2 city** visible as the visual ruler across the set.
- If zoom changes, start a new batch with its own calibration — do not mix.

### 5. What to OCR vs ignore

| Keep (blockers / seats) | Skip |
|-------------------------|------|
| City nameplates (`NN [ALLI] Name`) | Animals / mobs (despawn) |
| Alliance buildings (HQ, mills, mines, banners, traps) | Clearable small farms / harvest nodes (unless operator marks permanent) |
| Level badges on **immovable** RSS if they block seats | March arrows, rally bubbles, UI chrome |
| Terrain that never clears (if distinguishable) | Duplicate banners without an anchor neighbor |

Operator confirmation beats pure OCR merge — especially **banners** (many look identical).

### 6. Dedup before trust

- Same building appears in many overlapping shots; OCR will emit duplicates.
- Maintain an **inventory / match graph** (`batch3-element-inventory.yaml` pattern):
  - unique named anchors (Trap, HQ, Iron Mine, named cities)
  - operator `same_shots: […]` for ambiguous mills/RSS
  - never auto-collapse banners
- Prefer merge keys: **label text + approximate world xy + co-occurrence**, not label alone.

### 7. Footprints are typed, not OCR’d from text

OCR gives a point (label anchor). Footprint comes from kind:

| Kind | Default w×h |
|------|-------------|
| city | 2×2 |
| mill / banner / small building | 1×1 |
| trap / pitfall | ~3×3 |
| HQ | TBD (large; confirm) |

Store `kind` on every digitized hit; expand to a rect in world tiles for the sweeper.

### 8. Pixel↔world: use fit, then refine

- Bootstrapping MAT from **stitch placements × viewport deltas** worked (~117 px/tile edges, axes ≈ −35° / −146°).
- **Do not assume 45°.** Territory borders and world axes on screen are ≈ **±35°** here.
- Global MAT had **large residual** on some anchors (e.g. Trap→HQ) — OCR module should:
  1. place with MAT + viewport,
  2. snap/refine using 1–2 confirmed popup coords in-frame,
  3. report residual; fail loud if > N tiles.
- Thick blue borders are a good **orientation** cue, poor sole **phase** cue (stroke width ≈ half-tile; zigzag outer edge ≠ glow midline). Don’t block OCR on perfect grid lock.

### 9. Stitch lessons (if multi-shot coverage is needed)

- OpenCV `Stitcher_SCANS` alone was weak; **ORB translation + graph place** worked.
- Pair by **confirmed shared landmarks**, not by viewport proximity alone.
- Bad links poison the graph (e.g. 01→04 pulled south); encode allowed pairs + spatial notes.
- Save placements (`ox, oy`) + `canvas_min` beside the panorama so OCR can project shot hits onto the mosaic for QA overlays.

### 10. Capture discipline for future sessions

1. Same zoom; pan in a grid; leave **≥30% overlap**.
2. Export native resolution consistently (here 1080×2424).
3. Photograph or note search-bar coords if OCR will be flaky.
4. For critical blockers, one **popup screenshot** (exact X/Y) beats ten map pans.
5. Keep album URL + capture timestamp in the viewport YAML.

### 11. Module API sketch (when building it)

Suggested responsibilities (SRP):

| Unit | Job |
|------|-----|
| `mask_crop` | Apply fractional mask + crop → map band |
| `viewport_ocr` | Search-bar → `(x,y)` (+ fallbacks) |
| `label_ocr` | Find nameplates / building labels on cropped map |
| `world_project` | pixel + viewport + MAT → tile xy (+ residual) |
| `dedupe` | Match graph / inventory merge |
| `footprint` | kind → rect |
| `emit` | `blockers.yaml` / QA overlay PNG |

Config-driven: mask rects, MAT, kind sizes, skip-lists, valid coord ranges — **one place per decision** (see project soul / params style).

### 12. Definition of done for OCR on a site

- [ ] Every cropped shot has a trusted viewport
- [ ] Permanent structures listed once in world tiles with `kind` + footprint
- [ ] Known popup anchors match within ≤1 tile (or documented exception)
- [ ] QA overlay: labels drawn on panorama or per-shot with world xy
- [ ] Sweeper consumes the YAML without manual edits for the happy path

