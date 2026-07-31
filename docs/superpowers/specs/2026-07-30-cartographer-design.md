# Cartographer — Design

**Date:** 2026-07-30  
**Status:** Approved for implementation  
**Workspace:** `/Users/alexei/KS`  
**Related:** `assets/reference/bear-trap/FINDINGS.md` (OCR lessons), gather optimiser device layer

## Goal

Map a **local world region** around the player’s current BlueStacks viewport into a digitised **blocker / structure** layer (world tiles) for placement and later gather logic.

**Operator UX:** already looking at the area → `ks cartograph --radius 30` → auto sweep ±N tiles → YAML + QA overlay.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Center | Current viewport from search-bar OCR (`X,Y`) |
| Radius | Default **30** tiles; CLI `--radius` in **20…50** |
| Motion | **Coarse coord jumps** (~8–10 tile step) + **small swipes** for overlap |
| Output | `blockers.yaml`-compatible structures (kind + footprint) + QA overlay |
| Runtime | BlueStacks via existing `ks/device` ADB layer |
| Offline | `--fixture-dir` / `--dry-run` work without a device |
| Not in v1 | Gather marches, Discord, perfect iso-grid phase lock, daemon |

## Pipeline

```text
ADB screencap (or fixture PNG)
  → viewport OCR (native frame; search bar)
  → plan jump grid over [cx±R, cy±R]
  → for each sample:
        coord jump (calibrated taps) and/or swipe
        wait settle → screencap
        mask UI → crop map band
        label OCR (cities, alliance buildings, traps, blocking RSS)
        project pixel → world (viewport + MAT; refine if anchors known)
  → dedupe across samples
  → emit blockers YAML + QA overlay
```

Fail closed: unreadable center viewport → abort; single sample failure → log and continue.

## Modules

| Unit | Responsibility |
|------|----------------|
| `ks/device/adb.py` (+ connect helper) | Screencap / tap / swipe; BlueStacks `adb connect` |
| `ks/cartograph/mask.py` | Fractional mask + crop |
| `ks/cartograph/viewport.py` | Search-bar → `(x,y)` (reuse placement OCR) |
| `ks/cartograph/project.py` | pixel + viewport + MAT → world tile |
| `ks/cartograph/labels.py` | Label OCR → typed hits (kind stub / heuristics v1) |
| `ks/cartograph/dedupe.py` | Merge by label≈ + world xy |
| `ks/cartograph/sweep.py` | Jump grid + swipe offsets; dry-run plan |
| `ks/cartograph/pipeline.py` | Orchestration; fixture vs live |
| `ks cartograph` CLI | `--radius`, `--dry-run`, `--fixture-dir`, `--out` |

Config: extend `config/params.yaml` with `cartograph:` (radius, jump_step, mask ref, MAT path, navigation taps).  
Calibration seed: `assets/reference/bear-trap/ocr-calibration.yaml`.

## Footprints (from kind)

| Kind | w×h |
|------|-----|
| city | 2×2 |
| mill / banner / small building | 1×1 |
| trap | 3×3 |
| hq | 5×5 (TBD; match current blockers) |

## BlueStacks bring-up (when online)

1. BlueStacks running; ADB enabled (Settings → Advanced)  
2. `adb connect 127.0.0.1:<port>` (or cartograph connect helper)  
3. `python scripts/adb_smoke.py` → `artifacts/smoke.png`  
4. `ks cartograph --dry-run --radius 30` (plan only)  
5. Live cartograph once search-bar taps are calibrated  

## Success criteria

- [ ] Dry-run prints jump plan from a fake/fixture viewport  
- [ ] Fixture-dir run over batch3 produces a draft blockers YAML  
- [ ] Live smoke: connect + screencap + viewport OCR  
- [ ] Live cartograph covers ±R without requiring perfect grid lock  
