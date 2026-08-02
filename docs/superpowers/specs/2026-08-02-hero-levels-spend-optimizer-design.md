# Hero Levels Spend Optimizer — design

**Date:** 2026-08-02  
**Status:** Approved in brainstorm  
**Related:** `2026-08-02-gear-xp-spend-optimizer-design.md`, `2026-08-02-heroes-inventory-optimiser-ui-design.md` (Hero levels subtab)

## Goal

Given a bag of **Hero EXP** (single total) and an event target, allocate **hero levels** across the owned roster so the **event optimizer utility** (Swordland / Bear Trap expected points, or Arena score) is maximized. Lineups are **not** locked: after tentative level-ups, the existing event solver may pick different heroes.

This is a **knapsack-style** outer search over hero level spends, with the **inner value** of each pack equal to a full event optimize run — the same architecture as Gear XP spend, with heroes/levels instead of gear/enhancement.

## UI placement

Fill the existing Optimiser subtab (already reserved in the inventory/optimiser IA):

| Tool | Route | Role |
|------|-------|------|
| Event lineups | `/optimiser/events` | Sword / Bear / Arena formations |
| Gear XP spend | `/optimiser/gear-xp` | Fodder → piece upgrades for an event |
| Hero levels | `/optimiser/hero-levels` | Hero EXP → level-ups for an event |

**UI shape:** repeat Gear XP’s single-column layout (layout A):

1. Event target (same event/mode controls as Gear XP)
2. One numeric field: **Hero EXP available**
3. **Find best spends**
4. Results: baseline → best \(U\) delta · leftover EXP · ordered rows `hero · from→to level · XP used` · resulting formation summary
5. Propose only in v1 (no auto-write to `heroes.json`)
6. Optional **Open in Event lineups** with the winning mode preselected

Chrome: Apple-light Optimiser shell (Inventory | Optimiser + Event / Gear XP / Hero levels subtabs).

## Inputs

- **Event target:** Swordland (optional mode or best-of-modes), Bear Trap (rally_lead / joiner / best), Arena attack or defense — same as Gear XP
- **Hero EXP:** non-negative integer total available
- **Heroes:** current `heroes.json` (`name`, `level`, `power`, stars/pellets, etc.)
- **Gear + troops:** current stores used by the inner event solve (unchanged by this tool)

## Data to scrape / version

Public web tables (source URL + date in YAML headers), versioned under `config/hero_level_optimizer/` (parallel to `config/hero_gear_optimizer/`):

| Artifact | Purpose |
|----------|---------|
| `hero_level_xp_costs.yaml` | Incremental XP cost to reach each level (ladder + max level) |
| `hero_level_power.yaml` | Scale factor \(f(L)\) (or absolute power curve convertible to a factor) vs hero level |

Implementation scrapes/imports these before relying on them in tests; do not invent undocumented constants.

### Power rescale

When applying a level change \(L_{\text{old}} \rightarrow L_{\text{new}}\) to a hero with stored naked power \(P\):

\[
P' = \mathrm{round}\bigl(P \times f(L_{\text{new}}) / f(L_{\text{old}})\bigr)
\]

when both factors are positive — same spirit as `scale_power_for_star_change` / `star_progress_factor`.

**Eligibility:** a hero is a spend candidate only if `level` and `power` are both set and \(f(L)\) is defined for the current level. Ineligible heroes stay in the roster for the inner solve but never receive EXP in v1.

Stars/pellets remain as stored; this tool does not spend star resources.

## Core algorithm

### Outer problem

- **Decisions:** for each owned hero \(i\), target level (or how many +1 steps), subject to:
  - max level from the scraped XP ladder
  - cumulative XP cost along the ladder
  - total XP consumed ≤ Hero EXP bag
- **Objective:** maximize \(U(\text{event}, \text{heroes}', \text{gear})\) where \(\text{heroes}'\) is the roster after applying level spends and power rescale
- **\(U\):** existing solvers — `recommend` / `recommend_all_modes` expected points, or `optimize_arena` score

Exact enumeration is exponential. v1 search strategy (mirror Gear XP):

1. Build discrete **+1 level steps** per hero (each step = XP cost to next level)
2. **Beam / greedy-by-marginal-ΔU** over the EXP bag (evaluate \(U\) after applying batches of steps), with a small exact DP when bag and candidates are small
3. Optional ILP later if beam quality is insufficient; not required for v1

### Inner evaluation

For a candidate spend pack:

1. Clone hero records; bump `level`; rescale naked `power` via the scraped level curve
2. Run the selected event solver with updated heroes (gear assign as today)
3. Record utility + resulting lineup/formation

### Output

- Ordered spends: hero → from level → to level, XP used
- Leftover Hero EXP
- Baseline vs best \(U\), and the resulting heroes/formation
- Brief why where cheap (reuse explain hooks)

## Non-goals (v1)

- Stars / pellets / skill-level spends
- Typed EXP packs (single total only)
- Auto-writing levels into `heroes.json` (propose only; optional “apply” later)
- Multi-event joint optimize
- HQ gate enforcement beyond respecting max level in the scraped table
- Changing gear inventory as part of this tool

## API

- `GET /optimiser/hero-levels` — form + results UI (replace placeholder)
- `POST /api/optimize/hero-levels` — body: `event`, optional `mode`, `hero_exp` → JSON result pack
- Existing legacy `/optimize*` redirects stay as today

CLI later (optional): `ks-heroes spend-hero-xp --event … --exp N`

## Modules (proposed)

- `ks/heroes/optimize/spend_hero_xp.py` — allocate EXP bag (mirror `spend_xp.py`)
- Ladder helpers for hero level XP (mirror / share patterns from `xp_ladder.py`)
- Power rescale helper alongside `ks/heroes/ui/hero_power.py` (level factor, not stars)

## Testing

- Unit: XP bag accounting; level cost along ladder; cap enforcement; power rescale ratio
- Integration: small roster + tiny EXP → deterministic hero choice for a stubbed \(U\)
- Smoke: FastAPI `/optimiser/hero-levels` + `POST /api/optimize/hero-levels`; event solve still runs with mutated levels/power

## Acceptance

- User enters Hero EXP total and an event
- System returns which heroes to level (from→to), leftover EXP, and improved event utility / lineup
- Formation heroes may differ from the pre-spend lineup when that raises \(U\)
- Scraped XP + power-vs-level tables are checked in with source attribution
