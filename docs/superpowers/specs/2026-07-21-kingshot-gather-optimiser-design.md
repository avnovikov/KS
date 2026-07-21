# Kingshot Gather Optimiser — Design

**Date:** 2026-07-21  
**Status:** Approved for planning  
**Workspace:** `/Users/alexei/KS`

## Goal

Build a **hybrid** Kingshot optimiser: detect game state, recommend an action, and execute **only** after explicit terminal confirmation (`y`/`n`).

**v1 vertical slice:** gather when idle — if a march slot is free, propose a resource gather, confirm, then send the march.

## Non-goals (v1)

- Multi-hour unattended daemon
- Multi-account / multi-instance
- Full dailies, hunt, heal, or combat automation
- Memory reading, APK modification, or network interception
- Optimal pathfinding / distance-ranked node selection via OCR

## Approach

**Pure Python + ADB + OpenCV** (owned stack). Runtime preference on this Apple Silicon Mac:

1. BlueStacks (primary — reliable ADB for automation)
2. Google Play Games on Mac (fallback if BlueStacks is problematic)
3. Android Studio AVD (last resort)

Do **not** depend on Macro Automation Studio or recorded-macro-only scripts for the core loop.

## Architecture

```
Kingshot (emulator/native)
        ▲
        │ ADB (screencap / tap / swipe)
        ▼
   device layer
        ▼
   vision layer  (templates + optional OCR later)
        ▼
   gather policy  (state → Proposal | NothingToDo)
        ▼
   CLI confirm  (print plan → y/n)
        ▼
   action executor  (runs only if approved)
```

### Layer rules

| Layer | Responsibility | Must not |
|-------|----------------|----------|
| `device` | Connect ADB, capture screen, inject input | Decide what to do |
| `vision` | Locate UI via templates/regions; return matches + confidence | Tap or navigate |
| `policy` | Pure function: observations → `Proposal` or skip | Perform I/O or taps |
| `cli` | Present proposal; read `y`/`n` | Soft-approve without input |
| `executor` | Run an approved action plan (ordered taps/swipes) | Invent new goals |

**Fail closed:** unknown UI → skip + log; no taps.

## Gather loop (v1 behavior)

1. Connect ADB → capture screen  
2. Detect at least one free march slot  
3. If none free → print `idle: no free marches` and stop (or wait if loop mode added later)  
4. Navigate to map / gather search UI via known tap sequence  
5. Detect a gatherable resource node (templates; preference order from config)  
6. Build `Proposal`: resource type, match confidence, planned tap sequence, optional screenshot crop path for debugging  
7. Print proposal → wait for `y` / `n`  
8. On `y`: executor runs taps (select node → gather → confirm send)  
9. Re-capture → verify march started when possible; otherwise report `verify failed`

**v1 limits**

- One proposal per CLI invocation  
- Single calibrated resolution profile tied to emulator window size  
- First node above confidence threshold (preference order only; no distance scoring yet)

## Data model (conceptual)

```text
Proposal
  kind: "gather"
  resource: "food" | "wood" | "stone" | "gold" | ...
  confidence: float
  actions: list[Tap | Swipe | Wait]
  rationale: str          # human-readable for CLI
  debug_frame: path?      # optional saved screenshot

NothingToDo
  reason: str
```

## Configuration

`config/params.yaml` (illustrative keys):

- `adb.serial` / connection settings  
- `dry_run: true` by default (propose only; never tap until flipped)  
- `resources.preference_order`  
- `vision.templates` paths + match thresholds  
- `executor.max_taps_per_proposal`  
- `executor.tap_delay_ms` + jitter range  

## Project layout

```text
ks/
  device/       # ADB connect, screencap, tap, swipe
  vision/       # template matching, regions
  policy/       # gather idle → Proposal
  executor/     # run approved action plans
  cli.py        # entrypoint
assets/templates/
config/params.yaml
tests/          # fixture screenshots; no live game required for unit tests
docs/superpowers/specs/
```

## Stack

- Python 3.12+
- `adbutils` (or subprocess `adb`) for device I/O
- OpenCV for template matching
- PyYAML for config
- pytest for unit tests

## Safety

- Default `dry_run: true`  
- Unknown screen → no taps  
- Hard cap on taps per approved proposal  
- Small randomized delays between taps  
- Confirmation required for every live execution (no silent auto-approve in v1)

## Prerequisites (before implementing the loop)

1. Install BlueStacks (or Play Games) and Kingshot on this Mac  
2. Enable ADB; confirm `adb devices` lists the runtime  
3. Capture reference screenshots at the calibrated resolution for templates (city with free/busy marches, map with resource nodes, gather confirm UI)

## Success criteria (v1)

- From a known idle state with a free march, one CLI run can: detect → print a gather proposal → on `y` send a march (with `dry_run: false`)  
- With `dry_run: true`, the same path prints the proposal and performs zero taps  
- Unit tests cover policy decisions and template matching against fixture images  
- Unknown/mismatched UI never issues taps

## Out of scope notes

Game ToS and account risk are the user's responsibility. This design uses external vision + input only (no memory hacks). Prefer conservative pacing when live execution is enabled.
