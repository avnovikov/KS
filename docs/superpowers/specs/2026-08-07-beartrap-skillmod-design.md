# Bear Trap SkillMod v2 Design

**Date:** 2026-08-07  
**Status:** Approved for implementation  
**Branch:** `feature/beartrap-skillmod`  
**Workspace:** `.worktrees/feature-beartrap-skillmod`

## Goal

Replace the calibrated constant `base_skillmod ≈ 5.08` with the community
**op-bucketed SkillMod product** so host hero skills and assumed joiners
actually change Bear `rally_lead` damage.

## Formula (community)

```
SkillMod = research_skillmod
         × DamageUp
         × OppDefenseDown
         / max(OppDamageDown, ε)
         / max(DefenseUp, ε)

DamageUp = ∏_op (1 + sum_pct[op] / 100)
```

- Same `effect_op` → **add** percent values, then one `(1 + sum/100)`.
- Different ops → **multiply** those factors.
- Canonical ops: `101` Lethality DamageUp, `102` Attack DamageUp.
- No hero skills → DamageUp = 1 (guide baseline).

## Scope (this story)

1. **Host:** lineup catalog effects that are DamageUp / DefenseUp /
   OppDamageDown / OppDefenseDown — `applies_to` in `{expedition, widget}`,
   values from star-scaled `max_value`. Missing `effect_op` defaults:
   lethality kinds → 101, attack kinds → 102, defense kinds → 111.
2. **Joiners:** up to 4 assumed first skills from `beartrap_buffs.yaml`
   (default 2×101 + 2×102 at 25% = product 2.25).
3. **Research:** `research_skillmod` YAML knob (default `1.0`); replaces
   the old all-in-one `base_skillmod`.
4. **Non-goals:** chance/EV procs, OCR of live joiner roster, double-count
   audits vs gear expedition % (gear stays on `attack_per_troop` only).

## Wiring

- New helpers in `ks/heroes/optimize/bear_damage.py` (pure SkillMod math).
- `model._extract_bear_damage_solution` builds host buckets from chosen
  heroes + catalog, loads joiner buckets from buffs, computes skillmod.
- Breakdown exposes `skillmod`, `research_skillmod`, host/joiner bucket
  maps for UI/debug.

## Calibration note

Scores will drop vs the old 5.08 lump until `research_skillmod` is tuned
against a known rally. Default joiners (2+2) keep SkillMod in a realistic
band without inventing research.
