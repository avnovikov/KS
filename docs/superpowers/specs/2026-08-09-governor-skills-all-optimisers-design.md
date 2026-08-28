# Governor + skills across all optimisers — Design

**Date:** 2026-08-09  
**Status:** Ready for phased implementation  
**Idea:** [docs/ideas/conquest-combat-and-optimiser-skills.md](../../ideas/conquest-combat-and-optimiser-skills.md)  
**Backlog:** [docs/ideas/optimiser-governor-skills-backlog.md](../../ideas/optimiser-governor-skills-backlog.md)  
**Companion:** [2026-08-09-conquest-combat-sim-lite-design.md](2026-08-09-conquest-combat-sim-lite-design.md)

## Goal

One coherent treatment for **governor troop Atk%/Def%** (and set bonuses) and **leveled hero skills** across every combat optimiser, without inventing a second governor math path or mixing Conquest coeffs into Expedition SkillMod.

## Shared primitives (already exist or planned)

| Primitive | Location | Role |
|-----------|----------|------|
| `governor_troop_bonuses()` | `ks/heroes/governor_bonuses.py` | Per-troop Atk%/Def% + set bonuses from governor store |
| `family_percents` / `leveled_catalog_percents` | `ks/heroes/optimize/skill_effects.py` | Leveled expedition (and catalog) percents |
| `_conquest_percents` / `hero_contribution` | `ks/heroes/optimize/stat_contributions.py` | Family-aware contribution splits |
| Conquest sim-lite | **OG-01** → `ks/heroes/optimize/conquest_combat.py` | Arena/Conquest objective |
| Expedition SkillMod / Bear damage | `bear_damage.py`, model/recommend paths | Map/rally events |

Radiant Spire already consumes governor bonuses; it is the reference integration.

## Per-optimiser treatment

### Bear Trap (OG-03, GH #42)

| Aspect | Treatment |
|--------|-----------|
| Skill family | Expedition |
| Skills | Leveled expedition percents into damage/host strength; harden joiner/`effect_op` under OG-07 |
| Governor | Multiply or add troop Atk%/Def% into the same stats Bear damage already uses (Attack/Lethality/Defense/Health as applicable) via `governor_troop_bonuses()` |
| Done when | Upgrading governor Infantry/Cavalry/Archer piece changes Bear score in unit tests; empty store = baseline |

**Touch:** `ks/heroes/optimize/bear_damage.py`, recommend/bundle path for `beartrap`, tests under `tests/`.

### Swordland (OG-04, GH #43)

| Aspect | Treatment |
|--------|-----------|
| Skill family | Expedition |
| Skills | Already via `family_percents` → ILP contributions; OG-07 fixes kind gaps |
| Governor | Apply troop Atk%/Def% to expedition contribution strength / scenario stats consistently with Radiant proxy |
| Done when | Swordland recommend score moves with governor Atk% for troops used in the march |

**Touch:** `ks/heroes/optimize/model.py`, `recommend.py`, `stat_contributions.py` (expedition path), tests.

### Arena (OG-02 skills + OG-05 governor, GH #44)

| Aspect | Treatment |
|--------|-----------|
| Skill family | Conquest |
| Skills | Sim-lite SkillDPS × Toughness from leveled Conquest skills (OG-02) |
| Governor | Fold into escort toughness/offense and/or Atk_eff as specified below |
| Done when | Arena attack/defense rankings use sim-lite; governor on/off changes score |

**Touch:** `ks/heroes/optimize/arena.py`, `combat_formation.py`, conquest_combat helper.

### Conquest stages (OG-02 + OG-05, GH #45)

Same as Arena for skills and governor. Shared `combat_formation` base score must call sim-lite once.

### Gear XP (OG-06, GH #46)

| Aspect | Treatment |
|--------|-----------|
| Skill family | Via child event `U()` (sword / bear / arena) |
| Skills | Inherited from child optimisers |
| Governor | No separate Gear XP formula — child utilities already include governor after OG-03/04/05 |
| Done when | Fixture shows delta-U changes when governor store changes for a child mode |

**Touch:** `ks/heroes/optimize/spend_xp.py`, gear-xp API tests.

### Radiant Spire (done for governor v1)

| Aspect | Treatment |
|--------|-----------|
| Skill family | Expedition contributions for marches |
| Governor | Already wired |
| Follow-ups | Floors/MC are #37/#38 — out of this program’s first waves |

### Molten Fort (OG-08, GH #47)

| Aspect | Treatment |
|--------|-----------|
| Intent | Governor-primary mystic room optimiser (Radiant-like slice) |
| Implementation | [mystic-trial design](2026-08-09-mystic-trial-coliseum-molten-design.md) · `optimize_molten` + `/optimiser/molten-fort` |
| Stub done when | This section’s build criteria exist; no UI required yet |
| Build | Shared mystic-trial shell; seed 60/15/25; governor Atk%/Def% primary |

**Build criteria:**

1. Event config + optimiser page — **done**.
2. Objective uses governor troop bonuses as first-class input — **done**.
3. Heroes/gear from existing stores; light hero weight (0.15) — **done**.

## Governor application rules (Conquest family)

For Arena/Conquest after sim-lite:

1. **Hero sheet** (Hero Attack/Defense/Health) remains the base for Atk_eff / Def_eff / HP_eff.
2. **Escort / troop layer:** apply `governor_troop_bonuses()` Atk% and Def% to escort-facing stats that already appear in contribution explain, weighted by formation troop ratio when available.
3. Do **not** convert governor percents into Conquest skill coefficients.
4. Set bonuses (3pc Def / 6pc Atk) come only from `governor_troop_bonuses()` — never reimplemented in each optimiser.

Exact mixing weight for escort vs hero in the product score is a calibration knob; default: include escort Defense/Health in Toughness and escort Attack as a small additive term to SkillDPS (`+ EscortAtk_eff × escort_dps_weight` with `escort_dps_weight` default `0.15`) so pure troop tanks are not invisible.

## Expedition application rules

1. Governor Atk%/Def% combine with research/gear/hero expedition percents using the same composition style Radiant already uses (document the chosen multiply-vs-add rule once in `governor_bonuses` docstring and reuse).
2. SkillMod / effect_op stacking for joiners stays in Bear/SkillMod code paths (OG-07).
3. Conquest catalog ladders never feed expedition percents.

## Skills treatment summary

| Optimiser | Levels | Ladder | Formula family |
|-----------|--------|--------|----------------|
| Bear | Expedition levels | N/A (max×level/5 or catalog) | Troop + SkillMod |
| Swordland | Expedition | N/A | Expedition ILP |
| Arena / Conquest | Conquest levels | Hybrid (OG-01) | Sim-lite |
| Gear XP | Via children | Via children | Via children |
| Radiant | Expedition | N/A | Proxy + governor |
| Molten | Deferred to Molten plan | Deferred to Molten plan | Stub |

## Non-goals

- New GitHub issues for this board.
- Charms / pets / research inventory UIs.
- Full Conquest tick sim.
- ADB governor scrape.

## Testing strategy

- Per-optimiser unit tests with fixed hero + governor fixtures (on vs off).
- Shared helper tests for set bonuses (already present from Radiant) remain the SoT.
- Cross-mode: Gear XP fixture that enables governor and asserts U changes for sword or bear child.
- Conquest: see sim-lite design testing section.

## Implementation order

Follow [docs/ideas/optimiser-governor-skills-backlog.md](../../ideas/optimiser-governor-skills-backlog.md) dependency graph and the phased plan [2026-08-09-governor-skills-all-optimisers.md](../plans/2026-08-09-governor-skills-all-optimisers.md).
