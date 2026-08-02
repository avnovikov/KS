# Conquest Formation Optimizer — design

**Date:** 2026-08-02  
**Branch / worktree:** `feature/conquest-formation-optimizer`  
(`.worktrees/feature-conquest-formation-optimizer`, based on `feature/heroes-gear-xp`)  
**Status:** Math + CLI shipped; Event lineups UI wired (see `2026-08-02-conquest-event-lineups-ui-design.md`)

## Goal

Add a **Conquest** formation optimiser to the heroes toolkit that picks **5 heroes** in **2 front / 3 back** slots (same shape as Arena), assigns exclusive gear, and scores with Conquest-aware weights — by **extracting shared combat ILP** from Arena rather than duplicating it.

## Confirmed mechanics

| Fact | Decision |
|------|----------|
| Team size | **5 heroes**, slots `F1,F2,B1,B2,B3` |
| Skills | **Conquest skills only** (same layer as Arena) |
| vs Arena | Same formation + skill layer; Conquest is **PvE stage push** (one lineup, no attack/defense split) |
| Gear flats | Hero / Escort ATK·DEF·HP on the Conquest side of gear |
| Imbuements | R+40 / R+80 Conquest milestones **matter** (site Expedition optimizer skips them) |

**Correction:** Kingshot Mastery’s Conquest guide claiming “3 heroes” is treated as wrong (likely confused with 3-hero marches). Primary confirmation: player + community tips that discuss 4th/5th heroes for Conquest and Arena together.

## Architecture

```
combat_formation.py          # shared slots, result type, roles load, ILP
├── arena.py                 # thin: attack/defense profiles + public API
└── conquest.py              # thin: single Conquest profile + public API
```

### Shared core — `ks/heroes/optimize/combat_formation.py`

Move from `arena.py`:

- `FRONT`, `BACK`, `ALL_SLOTS`
- `CombatFormationResult` (mode, optional side, formation, heroes, score, gear_assignment, reasons, status, explanations)
- `load_combat_roles(path, catalog)` — placement YAML + heroes from `hero_catalog` (same pattern as today’s `load_arena_roles`)
- Base score, placement multipliers, provisional gear bonus
- `solve_combat_formation(...)` — PuLP binary assignment, one hero per slot, ≤1 slot per hero

**Compatibility:** `ArenaResult` remains as a thin alias / adapter around `CombatFormationResult` so existing Arena tests, CLI, explain, and spend_xp keep working without a big-bang rename.

### Mode profiles

| | Arena attack | Arena defense | Conquest |
|---|---|---|---|
| Config | `config/arena_roles.yaml` | `defense_placement` block | `config/conquest_roles.yaml` |
| Gear claim order | B2→F1→F2→B1→B3 | F1→F2→B2→B3→B1 | F1→F2→B2→B1→B3 (fronts first for stage walls) |
| Score extras | `arena_value` × stars + power + gear | + tank/heal tag bonuses | Same base + **ultimate skill level** bonus when scraped |
| Public API | `optimize_arena_attack/defense` | same | `optimize_conquest` |

Hero roles/tags/values: reuse catalog `arena_role` / `arena_value` / `arena_tags` for v1. Optional `conquest_value` later if catalog diverges.

### Ultimate skill bonus (Conquest-only)

When `HeroRecord.skills` is present, treat **slot 0** (top-left Conquest ultimate in collector convention) level as:

- missing / None → multiplier `1.0`
- level `L` → `1.0 + 0.04 * min(L, 10)` (tunable constant in conquest module)

Breadth-before-depth investment advice (5→8→10) stays documentation; the optimiser only uses scraped levels.

### Surfaces (in scope)

- CLI: `ks-heroes conquest` → JSON (mirror `ks-heroes arena`)
- Tests: shared-solver smoke; Conquest 5/2F+3B; ultimate bonus moves ranking when levels differ
- Config: `config/conquest_roles.yaml` (start from Arena attack placement + stronger infantry_front / front_tank_bonus)

### Out of scope

- UI / `/optimize` Conquest section
- Full battle simulation (DPS ticks, energy, cooldowns)
- Separate Conquest attack/defense
- Catalog `conquest_value` field (unless needed after first results)

## Sources & encoding limits

### Two combat layers (do not mix)

| Layer | Modes | Math available |
|-------|--------|----------------|
| Troop / Expedition | Map, rallies, Bear, Swordland | `Kills ≈ √Troops × (ATK×LET)/(DEF×HP) × SkillMod`; effect_op stacking |
| Hero / Conquest | **Conquest + Arena** | Skill tooltips + formation heuristics; **no public closed-form fight sim** |

This feature scores **hero Conquest combat**, not Expedition SkillMod.

### Where numbers live

| Need | Source | Trust |
|------|--------|-------|
| Formation size 5 / 2F+3B | Player + Arena guides + YT tips linking Conquest+Arena | High |
| Conquest skill multipliers & durations | kingshotdata.com, kingshotguide.com, in-game OCR | High for text; no global CD table |
| Gear Conquest flats + R+40/+80 | grindnstrat; our `imbuement_costs_and_bonuses.yaml` | High |
| Ultimate level priority ladder | Kingshot Mastery Conquest guide | Medium (apply to 5 heroes) |
| Troop damage / effect_op | kingshotguides.com; Optimizer; our event YAMLs | High for Expedition only |
| Roguelike pathing / “burner” teams | Lootbar “Conquest” articles | **Reject** (wrong mode shape) |
| “3 heroes in Conquest” | Mastery Conquest guide | **Reject** for formation size |

### Timing patterns (reference only — not simulated in v1)

From Conquest skill text: 0.5s multi-hit ticks; 1–2s stun/AS windows; 3–5s buffs; “heroes first” / back-row targeting; 50% HP thresholds (e.g. Amadeus). Auto-combat — no manual skill presses.

### Encode in v1 vs defer

| Encode | Defer |
|--------|--------|
| Shared 5-slot ILP | Full replay / DPS sim |
| Placement + gear order profiles | Exact cooldown / energy model |
| Ultimate level term from scraped skills | Per-frame target selection |
| `early_game_combat` gear profile | Closed-form win probability |
| Value Conquest imbuements in gear notes/docs | Roguelike burner tactics |

## Testing

- Existing Arena attack/defense tests must stay green after extract
- New: Conquest picks 5 distinct heroes, fills all slots
- New: higher ultimate level on otherwise equal hero increases selection preference
- CLI dry-run with fixture heroes.json writes `conquest_result.json`

## Success criteria

1. `optimize_conquest(...)` returns Optimal formation with 2F+3B
2. Arena API unchanged externally (`optimize_arena_*`, `ArenaResult.to_dict`)
3. `ks-heroes conquest --heroes …` works
4. No UI changes
