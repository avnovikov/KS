# Bear Trap Placement Optimiser — Design

**Date:** 2026-07-30  
**Status:** Ready for review  
**Workspace:** `/Users/alexei/KS`  
**Related:** [Bear Trap Plan Template (V3)](https://docs.google.com/spreadsheets/d/1q-f8cnhY7dAtwR_MjFVEYHJuk1uC6-yRAGVXhY3j9Sk/edit?usp=sharing)  
**Reference shots:** `assets/reference/bear-trap/`  
**Capture / OCR handoff:** `assets/reference/bear-trap/FINDINGS.md` (+ `ocr-calibration.yaml`)  
**Cartographer:** `docs/superpowers/specs/2026-07-30-cartographer-design.md` · plan `docs/superpowers/plans/2026-07-30-cartographer.md`

## Goal

Produce an **optimal dual-trap hive** for alliance [UTD] (State #2339) so that:

- ~**10–15 rally leaders** per event have short host cycles to a pitfall
- **20–40 joiners** (and dual-role players) get strong participation
- **BOTH / flex** players (two timezones) sit where they can shift between leaders/traps
- Placement **respects immovable blockers** (resource nodes, terrain, alliance buildings)

Deliverables: **solver results + sheet-style seat map + visual map**.

## Non-goals (v1)

- Live in-game teleport automation
- Hero / troop composition advice
- Exact OCR of every map tile (manual / screenshot blocker layer is OK for v1)
- Replacing Discord process / wave calling

## Locked decisions

| Topic | Decision |
|-------|----------|
| Layout style | Split-hive like V3: **two traps side-by-side**, dense 2×2 city packing |
| Extra space | ≥1 **extra middle row** for BOTH leaders + flex joiners |
| Anchor | **Hunting Trap 2 fixed** ≈ `X:701 Y:816` |
| Free variable | **New trap only** floats (sweep D / direction / small offset) |
| Search | **Full sweep** of D (and offsets), ranked by score |
| DO NOT TELEPORT pocket | **Ignored** (not reserved) |
| Capacity | ~**50–60 unique seats** (Hunt 1 / Hunt 2 / BOTH without double-counting bodies) |
| Outputs | Google-sheet-style grid **and** visual map |

## Geometry (from V3 + guides + operator)

- **City footprint: 2×2 tiles — primary unit.** Seat packing steps by 2; zoom is constant across shots, so a known city on a screenshot is the ruler for everything else.
- **Pitfall footprint:** ~3×3 tiles (verify against the city ruler if packing looks off)
- **Mills & banner:** 1×1 each (operator-confirmed)
- **V3 baseline spacing:** Trap centers ~**7** tiles apart ≈ trap + **two cities** between them
- Many cities ring each trap (not just two adjacent seats)
- **Camera / map view:** in-game world is shown **rotated ~45° (isometric)**. Orthogonal tile math (X/Y Chebyshev) still holds underneath; screenshot “left/up” must not be naively mapped without coord pins. Visual maps are rendered in isometric diamonds to match what players see.
- **Local blockers near Trap 2:** mills + banner **1×1** at popup coords; Plains HQ footprint still TBD

## Travel-time model

Distances are tile marches (Chebyshev or calibrated seconds-per-tile from one in-game sample).

**Leader host cycle**

```text
t_L = 2 * march(leader, trap)
```

**Joiner rally cycle** (assemble at leader, hit trap with rally, return home)

```text
t_J = march(joiner, leader) + march(leader, trap) + march(trap, joiner)
```

**Side-job:** after traps and a candidate seat set are chosen, pick ~10–15 leader seats per trap (lowest `t_L`, subject to balance) and assign joiners to the leader(s) that minimize `t_J` (allow top-2/top-3 flex for shift players).

### Default thresholds

| Symbol | Default | Meaning |
|--------|---------|---------|
| τ_L | ~4 tiles one-way (≈15s after calibration) | Leader inner ring |
| τ_J | 14 tile-steps full cycle (tune with seconds_per_tile) | Joiner cycle budget |
| Leader target | 10–15 per trap | Soft target; penalize below 10 |
| Preferred pose | E/W, D≈7 (V3) | Side-by-side worksheet style; N/S still scored |

## Sweep algorithm

1. Fix Trap 2 center at known coordinates (tile grid aligned to map).
2. For each candidate **new-trap** pose:
   - Distance `D ∈ {5…12}` tiles (center-to-center)
   - Direction ∈ {E, W, N, S}
   - Lateral offset ∈ `{-1, 0, +1}`
   - Reject if trap footprint hits blockers or leaves alliance-usable area
3. Enumerate valid **2×2 city anchors** that do not overlap traps, blockers, or other cities.
4. Score leaders / joiners / flex using `t_L` / `t_J`.
5. Rank poses; emit best maps + runner-up D options for alliance choice.

### Score (conceptual)

```text
L2, L1 = leader seats with t_L ≤ τ_L to trap 2 / trap 1
J     = joiner seats with best t_J ≤ τ_J
F     = seats with competitive t_J to 2+ leaders (or both traps)

score = w1 * min(|L2|, |L1|, 15)
      + w2 * (|L2| + |L1|)
      + w3 * |F|
      + w4 * |J|
      - penalty if min(|L2|, |L1|) < 10
```

Weights tunable in config; v1 defaults favor balanced leaders, then joiner participation, then flex.

## Blocker layer

- Seed from screenshots in `assets/reference/bear-trap/`
- Known fixed structures near site: Alliance Woodmill (east of Trap 2), Plains HQ ≈ `707,825`, resource nodes, rocky terrain
- Operator can supply additional zoomed screenshots; layer is edited as tile flags (`rss`, `building`, `blocked`)
- Seats and the **new** trap must not overlap blockers

## Outputs

1. **Ranked table** of (D, direction, offset, score, \|L2\|, \|L1\|, \|F\|, \|J\|)
2. **Sheet-style grid** (V3-compatible): numbered seats, Hunt 1 / Hunt 2 / BOTH name columns, resource/X cells marked
3. **Visual map** (HTML/SVG): traps, leaders, joiners, BOTH/flex, blockers, absolute coordinates
4. **Config YAML** for thresholds, weights, trap2 anchor, seconds-per-tile calibration

## Project layout (placement slice)

```text
ks/placement/           # pure geometry + scoring (no ADB)
  geometry.py           # footprints, march distance
  sweep.py              # new-trap sweep + seat pack
  assign.py             # leaders + joiner→leader assignment
assets/reference/bear-trap/
  blockers.yaml         # tile flags
  placement-map.html    # visual map output
  seats.csv             # sheet-style export
config/bear_trap.yaml   # thresholds / weights / anchor
tests/test_placement_*.py
docs/superpowers/specs/2026-07-30-bear-trap-placement-design.md
```

## Success criteria

- Sweep returns a ranked list; top layout has ≥10 leader-quality seats per trap when the local map allows
- Joiner assignment uses full `t_J = to_leader + leader_to_trap + trap_to_joiner`
- Visual map + seat CSV generated from the same layout object
- Unit tests cover distance math, packing non-overlap, and “closer D merges leader rings / farther D kills flex” score behavior on a synthetic empty map

## Open calibrations (do not block v1 structure)

- Exact seconds-per-tile from one measured march near 701,816
- Precise blocker digitization (more zoomed screenshots on request)
- Whether new trap must stay inside current blue territory diamond (assume yes unless alliance says otherwise)
