# Gear XP Spend Optimizer — design

## Goal

Given free enhancement fodder and an event target, allocate XP across owned gear so the **event optimizer utility** (Sword/Bear expected points, or Arena score) is maximized. Lineups are **not** locked: after tentative upgrades, the existing event solver may pick different heroes.

This is a **knapsack-style** outer search over gear XP spends, with the **inner value** of each pack equal to a full event optimize run.

## UI placement

Optimize **hub** (approach 1):

| Tool | Route (proposed) | Role |
|------|------------------|------|
| Event lineups | `/optimize` (existing) | Sword / Bear / Arena formations |
| Gear XP spend | `/optimize/gear-xp` (new) | Fodder → piece upgrades for an event |

Shared nav: Gear | Heroes | Optimize hub (cards linking to tools). Room for more optimizers later.

## Inputs

- **Event target:** Swordland (optional mode or best-of-modes), Bear Trap (rally_lead / joiner / best), Arena attack or defense
- **Fodder counts** (XP from `config/hero_gear_optimizer/pieces_and_stats.yaml` → `fodder_xp_values`):
  - grey gear → 10
  - green gear → 30
  - blue gear → 60
  - purple gear → 150
  - 100-pt parts (`xp_part_purple_100`) → 100
- **Inventory:** current `gear.json` (piece id, troop, slot, rarity, enhancement_level)
- **Heroes:** current `heroes.json` (for inner event solve)

Spend respects **typed bag** (cannot convert grey into purple); leftover of each type is reported.

## Core algorithm

### Outer problem (knapsack extension)

- **Decisions:** for each owned piece \(i\), how much Enhancement XP to add (or equivalently target enhancement level), subject to:
  - rarity caps from `enhancement_xp_costs.yaml` (`epic_max` 80, `mythic_max` 100, `red_max` 200)
  - cumulative XP cost ladder (level → level+1 costs)
  - total XP consumed per fodder type ≤ counts × unit XP
- **Objective:** maximize \(U(\text{event}, \text{heroes}, \text{gear}')\) where \(\text{gear}'\) is inventory after applying spends
- **\(U\):** existing solvers — `recommend` / `recommend_all_modes` expected points, or `optimize_arena` score

Exact enumeration is exponential. v1 search strategy:

1. Build discrete **level-up steps** per piece (each step = XP cost to next level, marginal candidates)
2. **Beam / greedy-by-marginal-ΔU** over the typed bag (evaluate \(U\) after applying a batch of steps), with a small exact DP when total XP and candidate pieces are small
3. Optional ILP later if beam quality is insufficient; not required for v1

### Inner evaluation

For a candidate spend pack:

1. Clone gear records; bump `enhancement_level` / recompute piece power where the UI already derives power from rarity+enhancement+mastery
2. Run the selected event solver with updated gear (exclusive/class assign as today)
3. Record utility + resulting lineup/formation

### Output

- Ordered spends: piece → from level → to level, XP used, fodder types consumed
- Leftover fodder by type
- Baseline vs best \(U\), and the resulting heroes/formation
- Brief why: which pieces got XP and final lineup (reuse explain hooks where cheap)

## Non-goals (v1)

- Mastery / forgehammers / mithril / red imbuement
- Auto-writing upgrades into `gear.json` (propose only; optional “apply” later)
- Multi-event joint optimize
- Treating purple 150 and 100-pt parts as interchangeable beyond their XP values in the bag

## Data dependencies (existing)

- `fodder_xp_values` in `pieces_and_stats.yaml`
- `enhancement_xp_costs.yaml` level ladder + caps
- `build_profiles.yaml` (gear scoring inside assign)
- Event YAMLs + arena roles + hero catalog
- Gear/heroes stores used by Optimize UI

## API (proposed)

- `GET /optimize` — hub page
- `GET /optimize/gear-xp` — form + results UI
- `POST /api/optimize/gear-xp` — body: event, side/mode, fodder counts → JSON result pack

CLI later: `ks-heroes spend-xp --event … --grey N …`

## Testing

- Unit: XP bag accounting; level cost along ladder; cap enforcement
- Integration: small inventory + tiny fodder → deterministic piece choice for a stubbed \(U\)
- Smoke: FastAPI hub + gear-xp route; event solve still runs with mutated levels

## Acceptance

- User enters grey/green/blue/purple + 100-pt counts and an event
- System returns where XP should go and the improved event utility / lineup
- Heroes may differ from the pre-spend lineup when that raises \(U\)
