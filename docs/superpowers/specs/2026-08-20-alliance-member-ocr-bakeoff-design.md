# Alliance Member OCR Bake-off Design

**Date:** 2026-08-20  
**Status:** Approved — plan at `docs/superpowers/plans/2026-08-20-alliance-member-ocr-bakeoff.md`  
**Workspace:** `/Users/alexei/KS`  
**Primary corpus:** `artifacts/alliance-r4-r3-scan/`  
**Related:** `artifacts/alliance-r4-r3-scan/export_xlsx.py` (stability rules), `scan_70.py` (live EasyOCR path)

## Goal

Improve alliance member list OCR (player **names** + **power**) by running an **offline** bake-off of multiple OCR engines and preprocess/settings, scored against a small **hand-confirmed gold set** mined from existing OCR-instability rules — before changing the live scan.

Success = measurable lift vs current EasyOCR baseline on both **precision and recall** for name+power rows.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Scope | Alliance member lists only (R5 members page + R4/R3/R2 expands) |
| Approach | Offline harness first; no live `scan_70` change in this phase |
| Eval construction | Auto-mine unstable cases → hand-confirm gold crops |
| Engines (v1) | EasyOCR (baseline), Tesseract, PaddleOCR, RapidOCR, plus one modern stack (docTR **or** Surya — pick during install spike) |
| Settings | Sweep preprocess + engine knobs, not library swap alone |
| Scoring semantics | Reuse production pairing (`pair_members` / `parse_power` / `ocr_edit_distance`) so wins transfer to the scan |
| Out of scope | Cartograph map labels, viewport `X:Y`, production ensemble, GPU requirement |

## Problem framing

KingShot UI text is intentionally hard for OCR. The alliance scan already detects instability via:

- `ocr_edit_distance` + `OCR_MERGE_POWER_GAP` (near-duplicate name merges)
- Day-to-day / reocr comparison pairs labeled `LEVENSHTEIN` in `export_xlsx.pair_alliance_players`
- Scroll overlap / reocr JSON variants (`names-*.json`, `*.reocr.json`)

Those signals point at **hard cases** without labeling the entire corpus (~800+ member screenshots).

## Architecture

```text
names-*.json ──► mine_unstable ──► candidates.csv ──► hand confirm ──► gold.json + crops/
                                                                              │
screenshots *.png ────────────────────────────────────────────────────────────┘
                                                                              │
                                    engines × preprocess grid ◄───────────────┘
                                              │
                                         run_bench
                                              │
                                    report.json + summary.md + failures/
```

### Components

| Unit | Responsibility |
|------|----------------|
| `mine_unstable` | Diff listings with existing pairer; emit unstable name/power candidates + suggested shot paths |
| `gold` store | Confirmed expected `{name, power}` tied to a crop (or full-frame ROI) |
| `engines/*` | Adapters → common hit schema `{text, conf, box_xyxy}` |
| `preprocess` | Deterministic transforms keyed by setting id |
| `run_bench` | Cross product engine × settings on gold; write metrics + failure gallery |
| `pair_score` | Apply `pair_members`-compatible pairing then score vs gold |

**Package location:** `tools/alliance_ocr_bench/` (scripts + optional deps). Keep adapters out of `ks/cartograph` until a winner is promoted. Import pairing/parse helpers from the alliance scan modules or a thin shared extract — do not fork Levenshtein rules.

## Gold mining

1. Choose two snapshots (default candidates):
   - `names-2026-08-18T0042.json` vs `names-2026-08-18T2035.json`, and/or
   - raw vs `*.reocr.json` for the same timestamp.
2. Run the existing alliance player pairer; keep rows with match kind `LEVENSHTEIN`, plus optional near-dupes under `OCR_MERGE_POWER_GAP`.
3. For each unstable player, resolve screenshot candidates:
   - `{tag}-r4-*.png`, `{tag}-r3-*.png`, `{tag}-r2-*.png`, `{tag}-members.png`
4. Emit `candidates.csv` with: tag, rank hint, suggested shot, both name spellings, powers, edit distance.
5. Human confirms ~**30–80** rows into `gold.json`:
   - `id`, `shot` (relative path under artifacts), `roi` (x0,y0,x1,y1) or null for default member band, `name`, `power`
6. Prefer cases where the correct spelling is visually unambiguous on the PNG.

Gold is the only ground truth. Unstable mining never auto-labels the “right” name without confirmation.

## Engines and settings grid

### Engines

| Engine | Role |
|--------|------|
| EasyOCR | Baseline (matches live `scan_70`) |
| Tesseract (`pytesseract`) | Already in repo; digit-friendly control |
| PaddleOCR | Strong scene-text candidate |
| RapidOCR | Lightweight ONNX alternative |
| docTR **or** Surya | Modern recognizer; choose whichever installs cleanly on macOS arm64 without blocking the rest |

Missing optional engines skip with an explicit `skipped` status in the report (do not fail the whole bench).

### Preprocess / settings (first grid)

Each cell is a named profile, e.g. `gray_x2_thr`, `clahe_x3`, `raw_x1`.

| Axis | Values (v1) |
|------|-------------|
| Color | raw BGR→RGB, grayscale, adaptive/OTSU binary, optional invert |
| Scale | 1×, 2×, 3× |
| Contrast | none, CLAHE |
| EasyOCR `conf_min` | 0.18, 0.25 (current), 0.35 |
| Tesseract PSM | 6, 7, 11 (where used) |
| ROI | default member band (`y0/y1/x0/x1` as in `ocr_hits`) vs gold crop ROI |

Keep total cells bounded: prefer ~**engines × ~8–12 preprocess profiles**, not a combinatorial explosion. Document the exact matrix in the bench README when implemented.

## Metrics

For each engine×profile on the gold set:

| Metric | Definition |
|--------|------------|
| Name exact | Normalized exact match to gold name |
| Name near | `ocr_edit_distance` within existing limits |
| Power exact | Parsed power == gold (after `parse_power` semantics) |
| Power ±0.1 / ±1.0 | Absolute gap buckets (M/K parsing must match production) |
| Row recall | Gold rows with a paired name+power hit that passes name-near + power±1.0 |
| Row precision | Predicted paired rows that match some gold row under the same rules |
| Latency | Wall time per image (median) |

**Primary ranking key:** row F1 (precision/recall harmonic mean) under name-near + power±1.0.  
**Secondary:** name exact rate, then latency.

Baseline row is EasyOCR + current crop/conf (`conf_min=0.25`, default band).

## Outputs

Under `artifacts/alliance-ocr-bench/` (gitignored data) or `tools/alliance_ocr_bench/out/`:

- `report.json` — full metrics matrix
- `summary.md` — ranked table + top failures
- `failures/` — side-by-side crops with expected vs predicted text
- `gold/` — confirmed set (small; may be committed if free of sensitive data — default: keep under artifacts unless user opts in)

## Error handling

- Engine import/init failure → mark skipped; continue.
- Unreadable shot → mark error for that gold id; do not abort.
- Empty OCR → count as miss (recall down), not crash.
- Assert gold schema on load (required keys, power > 0, shot exists).

## Testing

- Unit: normalize/score helpers; gold schema validation; preprocess profile ids stable.
- Smoke: run bench on ≤5 gold rows with EasyOCR + Tesseract only in CI if heavy deps are optional.
- Manual: regenerate summary after gold confirm; sanity-check failure gallery.

## Phase 2 (explicitly later)

After a clear winner:

1. Wire winning engine×profile into `scan_70` / `reocr_from_shots` behind a config flag.
2. Re-run reocr on full screenshot corpus; compare listings with existing export comparison sheet.
3. Only then consider multi-engine ensemble.

## Verification (definition of done for phase 1)

- [ ] Unstable candidates mined with existing Levenshtein/power-gap rules
- [ ] Gold set confirmed (≥30 rows) with shot + expected name/power
- [ ] ≥3 engines runnable locally besides EasyOCR baseline (or documented skips)
- [ ] Settings grid includes preprocess variants, not defaults-only
- [ ] Report ranks configs by row F1 vs EasyOCR baseline
- [ ] No live scan behavior change without a follow-up decision
