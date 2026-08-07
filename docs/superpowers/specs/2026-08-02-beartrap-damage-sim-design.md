# Bear Trap Damage Simulator Design

**Date:** 2026-08-02  
**Status:** Approved for implementation  
**Workspace:** `.worktrees/feature-beartrap-damage-sim`  
**Branch:** `feature/beartrap-damage-sim`

## Goal

For Bear Trap `rally_lead`, replace the Swordland combat-rate **proxy** with the community **10-round Bear damage formula** so `expected_personal_points` ≈ single-rally **damage score**.

Calibration anchor (user observation):

| Field | Value |
|-------|-------|
| March | ~80 245 / 82 930 |
| Formation | ~32 / 32 / 32 |
| Power | ~5 806 585 |
| Score | ~180 000 (single rally) |

## Locked decisions

| Topic | Decision |
|-------|----------|
| Formula source | [kingshotguides Bear damage mechanics](https://kingshotguides.com/guide/bear-trap-damage-mechanics-and-example-simulation/) |
| Scope | `rally_lead` under event `beartrap` only; other modes keep linear proxy |
| Hero pick | Existing ILP maximizing `hero_strength` (attack widget, one-per-type) |
| Troop fill | Post-solve greedy by marginal damage (tier-aware inventory) |
| SkillMod | Config knobs + map from lineup `hero_strength`; joiner stack = YAML multiplier |
| RNG skills | Constant SkillMod (guide no-RNG case) |
| Workspace | Fresh worktree from `main` |

## Formula

Bear: 5000 infantry, Defense 10, Health 83.3333 → `bear_defense = 8.33333`.

Per troop type:

```
attack_per_troop = base_attack × (1 + trap_attack_bonus)
                 × (lethality / 100) × skillmod × (1 + host_attack_pct)
army = sqrt(n_type × 5000)
round_damage_type = army × attack_per_troop / bear_defense / 100
                   × (1.10 if archers else 1.0)
score = ceil(10 × sum(round_damage_type))
```

**Regression fixture:** 6000/6000/6000 T6 TG0, trap +25%, skillmod=1 → **16797**.

## Architecture

```
ks/heroes/optimize/bear_damage.py   # simulate, greedy fill, skillmod helpers
config/beartrap_buffs.yaml          # trap_level, skillmod knobs, calibration
model.py                            # beartrap rally_lead path
cli.py                              # bear-damage + recommend breakdown
```

## SkillMod (v1 — superseded)

Superseded by `docs/superpowers/specs/2026-08-07-beartrap-skillmod-design.md`.
SkillMod is now an op-bucket product (research × host catalog DamageUp ×
assumed joiners), not a single calibrated constant.

## Non-goals (v1)

- Auto OCR of research / joiner first skills
- Multi-march event totals
- Chance-based hero procs
- Changing non-beartrap modes
