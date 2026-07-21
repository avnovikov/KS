# Kingshot Gather Optimiser — Design

**Date:** 2026-07-21  
**Status:** Approved for planning (revised: throughput scoring)  
**Workspace:** `/Users/alexei/KS`

## Goal

Build a **hybrid** Kingshot optimiser: detect game state, recommend an action, and execute **only** after explicit terminal confirmation (`y`/`n`).

**v1 vertical slice:** gather when idle — if a march slot is free, score candidate resource tiles by **effective RSS/time** (gather time vs round-trip march time, haul capped by march load), propose the best tile, confirm, then send the march.

## Non-goals (v1)

- Multi-hour unattended daemon
- Multi-account / multi-instance
- Full dailies, hunt, heal, or combat automation
- Memory reading, APK modification, or network interception
- Auto-calibrating every account buff from UI on day one (manual YAML rates/load OK for v1)

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
   gather policy  (candidates → score → Proposal | NothingToDo)
        ▼
   CLI confirm  (print plan + score breakdown → y/n)
        ▼
   action executor  (runs only if approved)
```

Scoring lives in a pure `policy/scoring` module (no I/O) so it is unit-tested with fixture numbers.

### Layer rules

| Layer | Responsibility | Must not |
|-------|----------------|----------|
| `device` | Connect ADB, capture screen, inject input | Decide what to do |
| `vision` | Locate UI; read tile amount / march time / load via OCR or typed fields | Tap or navigate |
| `policy` | Score candidates → best `Proposal` or skip | Perform I/O or taps |
| `cli` | Present proposal; read `y`/`n` | Soft-approve without input |
| `executor` | Run an approved action plan (ordered taps/swipes) | Invent new goals |

**Fail closed:** unknown UI → skip + log; no taps.

## Scoring model (distance vs amount)

Arbitrary `w_a` / `w_d` weights are replaced by **account rates**. Effective throughput is:

```text
haul          = min(tile_amount, march_load)          # load caps what you can take in one go
t_gather      = haul / gather_rate                    # gather_rate is RSS/sec for that resource
t_march_one   = distance / march_speed                # or one-way time from the march UI
t_march_round = 2 * t_march_one                       # back and forth
score         = haul / (t_gather + t_march_round)     # effective RSS per unit time
```

Pick the candidate with the **highest `score`**. Print the breakdown in the CLI rationale (`haul`, `t_gather`, `t_march_round`, `score`).

### Mechanics notes (from public guides / community tables)

- Haul is capped by **troop load** (tier + count + Growth research). Always prefer tiles you can fully clear when possible; leftover tile fragments are poor follow-ups ([Kingshot Mastery farm / gathering guides](https://kingshotmastery.com/guides/kingshot-farm-account-guide)).
- **Gathering speed** (Economy research, Rare gathering heroes Olive/Forrest/Edwin/Seth, alliance/island/city bonuses) raises `gather_rate`. Higher tile **level** mainly raises `tile_amount`, not a separate magic gather multiplier ([gathering guide](https://kingshotmastery.com/guides/resource-gathering-events)).
- Round-trip march time matters for active play: a nearer tile you can clear often beats a distant richer tile on RSS/time.
- Community reference tile sizes / baseline gather durations (verify in-game; treat as defaults only): [kingshot.fun Resource Gathering Calculator](https://kingshot.fun/Calculators/ResourceGathering/default.html) — e.g. L1 Bread/Wood 70K ~6m; L5 1.2M ~1h30m; L8 14M ~15h50m (boosted times shorter).

### Data sources for v1

| Input | v1 source | Later |
|-------|-----------|--------|
| `tile_amount` | OCR from tile info / search result | same |
| `distance` or `t_march_one` | OCR march-time preview when selecting a tile (preferred over raw distance) | same |
| `march_load` | `params.yaml` (user-measured from formation UI) | OCR formation panel |
| `gather_rate` by resource | `params.yaml` (derive from full-tile time ÷ amount, or Governor bonuses) | OCR / calibrated from known tile clears |

If OCR fails for a candidate, drop that candidate (fail closed) rather than guess.

## Gather loop (v1 behavior)

1. Connect ADB → capture screen  
2. Detect at least one free march slot  
3. If none free → print `idle: no free marches` and stop  
4. Navigate to map / resource search UI via known tap sequence  
5. Collect **N** candidate tiles (configurable; same preferred resource filter optional)  
6. For each candidate: read `tile_amount` + one-way march time (or distance); compute `haul`, times, `score`  
7. Build `Proposal` for the top-scoring tile (actions + score breakdown)  
8. Print proposal → wait for `y` / `n`  
9. On `y`: executor runs taps (select node → gather → confirm send)  
10. Re-capture → verify march started when possible; otherwise report `verify failed`

**v1 limits**

- One proposal per CLI invocation  
- Single calibrated resolution profile tied to emulator window size  
- Small candidate set (e.g. top search results), not full-map scan  
- Account `march_load` / `gather_rate` from YAML until UI reading is added  

## Data model (conceptual)

```text
GatherCandidate
  resource: "bread" | "wood" | "stone" | "iron"
  tile_amount: float
  march_time_one_way_s: float
  vision_confidence: float

ScoredGather
  candidate: GatherCandidate
  haul: float                 # min(tile_amount, march_load)
  t_gather_s: float
  t_march_round_s: float
  score: float                # haul / (t_gather + t_march_round)

Proposal
  kind: "gather"
  scored: ScoredGather
  actions: list[Tap | Swipe | Wait]
  rationale: str              # includes score breakdown for CLI
  debug_frame: path?

NothingToDo
  reason: str
```

## Configuration

`config/params.yaml` (illustrative keys):

- `adb.serial` / connection settings  
- `dry_run: true` by default (propose only; never tap until flipped)  
- `resources.preference_order` (optional soft filter before scoring)  
- `account.march_load`  
- `account.gather_rate_per_sec` per resource (`bread` / `wood` / `stone` / `iron`)  
- `scoring.candidate_limit`  
- `vision.templates` paths + match thresholds  
- `executor.max_taps_per_proposal`  
- `executor.tap_delay_ms` + jitter range  

## Project layout

```text
ks/
  device/       # ADB connect, screencap, tap, swipe
  vision/       # template matching, regions, OCR helpers
  policy/       # gather idle → candidates → score → Proposal
  policy/scoring.py  # pure haul/time throughput math
  executor/     # run approved action plans
  cli.py        # entrypoint
assets/templates/
assets/reference/  # optional community tile tables for defaults
config/params.yaml
tests/          # fixture screenshots + scoring unit tests
docs/superpowers/specs/
```

## Stack

- Python 3.12+
- `adbutils` (or subprocess `adb`) for device I/O
- OpenCV for template matching
- OCR (Tesseract or equivalent) for amounts / march times
- PyYAML for config
- pytest for unit tests (scoring needs no device)

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

- From a known idle state with a free march, one CLI run can: detect candidates → score by haul/(gather + round-trip march) → print the best proposal with breakdown → on `y` send a march (`dry_run: false`)  
- With `dry_run: true`, the same path prints the proposal and performs zero taps  
- Unit tests prove scoring: load cap, round-trip march penalty, and “nearer smaller tile beats distant huge tile” when rates imply it  
- Unknown/mismatched UI never issues taps  

## Out of scope notes

Game ToS and account risk are the user's responsibility. This design uses external vision + input only (no memory hacks). Prefer conservative pacing when live execution is enabled.
