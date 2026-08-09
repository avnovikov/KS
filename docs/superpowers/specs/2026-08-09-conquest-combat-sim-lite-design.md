# Conquest combat sim-lite — Design

**Date:** 2026-08-09  
**Status:** Ready for implementation (OG-01 / OG-02)  
**Idea:** [docs/ideas/conquest-combat-and-optimiser-skills.md](../../ideas/conquest-combat-and-optimiser-skills.md)  
**Backlog:** [docs/ideas/optimiser-governor-skills-backlog.md](../../ideas/optimiser-governor-skills-backlog.md)

## Goal

Replace the Conquest scoring proxy that folds skill **Damage Up / AoE Damage Up** into Hero/Escort Attack flats with a **deterministic sim-lite** that matches public skill semantics: skills deal `Attack × X` damage, while Attack%/Defense%/AS/Heal/EDT are separate modifiers.

## Problem with current code

In `ks/heroes/optimize/stat_contributions.py`, `_CONQUEST_KIND_LABELS` maps:

- `damage_up`, `aoe_damage_up` → `("Hero Attack", "Escort Attack")`
- `attack_speed_up`, `crit_rate_up` → Hero Attack
- `heal_up` → Hero/Escort Health

That treats Amadeus ultimate **Damage Up 224** like **+224% Attack**, which overstates Attack and ignores multi-hit, AoE, cast rate, and Enemy Damage Taken. Expedition `SkillMod` / `effect_op` math must **not** be reused here.

## Modes in scope

| Mode | Skills | Consumer |
|------|--------|----------|
| Conquest stages | Conquest tab only | `optimize_conquest` → `combat_formation` |
| Arena | Conquest tab only | `optimize_arena` → `combat_formation` |

Expedition (Swordland, Bear, Radiant map marches, joiners) stays on troop stats + SkillMod.

## Kind taxonomy

| Kind (catalog / `skill_effects`) | Bucket | Role in sim-lite |
|----------------------------------|--------|------------------|
| `damage_up` | coeff | Skill hit coefficient X in `Attack × X/100` |
| `aoe_damage_up` | coeff | Same, multiplied by `aoe_targets` |
| `attack_up` | offense_stat | Raises effective hero Attack |
| `defense_up` | toughness_stat | Raises effective Defense |
| `damage_taken_down` | toughness_stat | Reduces incoming |
| `opp_damage_down` | toughness_stat | Treat as incoming reduction for ranking |
| `health_up` | toughness_stat | Raises effective HP |
| `heal_up` | heal | Expected heal contribution |
| `attack_speed_up` | rate | Multiplies cast/auto rate |
| `crit_rate_up` | crit | Expected damage factor |
| Enemy damage taken (label → kind, e.g. `enemy_damage_taken_up`) | amp | Multiplies outgoing SkillDPS |

Add `enemy_damage_taken_up` to `skill_effects` kind map if missing; do not dump it into Attack flats.

## Hybrid ladders

Catalog skill effect (or skill row) may include:

```yaml
# example shape — exact field nesting follows existing CatalogSkill / effects schema
ladder: [160, 176, 192, 208, 224]   # levels 1..5
# optional notes for levels 6..10 when known:
ladder_notes: "Mastery: ~+30% 5→8, ~+15% 8→10; UI levels still 1–5 until extended"
```

**Resolution:**

```text
if ladder is present and 1 <= level <= len(ladder):
    value = ladder[level - 1]
else:
    value = max_value * (level / 5)
```

**Seed in first coding PR (examples, not exhaustive):**

| Hero | Skill | Kind | Ladder 1→5 |
|------|-------|------|------------|
| Amadeus | Combo Slash | `damage_up` | 160, 176, 192, 208, 224 |
| Vivian | Gilded Barrage | `aoe_damage_up` | 180, 198, 216, 234, 252 |
| Petra | Dichotomy | `damage_up` | 270, 297, 324, 351, 378 |

Cite Kingshot Mastery Conquest guide as source in catalog/seed script comments.

## Sim-lite formulas

Constants (config or module defaults; calibrate via OG-09):

| Symbol | Default | Meaning |
|--------|---------|---------|
| `α` | `0.5` | Toughness exponent in product score |
| `aoe_targets` | `2.0` | Default AoE multiplicity when kind is `aoe_damage_up` |
| `hits_per_cast` | from catalog or `1` | e.g. Amadeus Combo Slash → `3` |
| `cast_rate` | `1.0` | Relative casts per unit time (ultimate vs basic can differ later) |
| `crit_mult` | `2.0` | Assumed crit damage multiplier for expectation |

```text
Atk_eff = HeroAttack × (1 + Σ attack_up / 100)

For each Conquest skill with a coeff kind:
  coeff = leveled_value(skill)          # ladder or linear
  rate  = cast_rate × (1 + Σ attack_speed_up / 100)
  aoe   = aoe_targets if kind == aoe_damage_up else 1.0
  hits  = hits_per_cast(skill) or 1
  crit_E = 1 + (Σ crit_rate_up / 100) × (crit_mult - 1)
  amp   = 1 + Σ enemy_damage_taken_up / 100

  skill_dps_i = Atk_eff × (coeff / 100) × hits × rate × aoe × amp × crit_E

SkillDPS = Σ skill_dps_i

Def_eff = HeroDefense × (1 + Σ defense_up / 100)
HP_eff  = HeroHealth × (1 + Σ health_up / 100)
DR      = clamp(Σ damage_taken_down + Σ opp_damage_down, 0, 90) / 100
HealExp = f(heal_up, Atk_eff)   # default: Atk_eff × (Σ heal_up / 100) × heal_rate
                                 # if skill is % max HP heal, use HP_eff × (heal_up/100) instead (catalog flag)

Toughness = (HP_eff + HealExp) × (1 + Def_eff / DefScale) / (1 - DR)
            # DefScale default 10000 — keeps Defense from dominating; document in code

Score = SkillDPS × (Toughness ** α)
```

Formation score: sum (or weighted sum) of hero Scores with existing role/slot multipliers in `combat_formation.py` (front survival tags stay).

## API sketch

```python
@dataclass(frozen=True)
class ConquestCombatBreakdown:
    atk_eff: float
    skill_dps: float
    toughness: float
    score: float
    incomplete: bool

def conquest_hero_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    *,
    catalog: ...,
    alpha: float = 0.5,
) -> ConquestCombatBreakdown:
    ...
```

Inputs: naked/OCR conquest flats for Hero Attack/Defense/Health, gear conquest flats already merged by caller or inside helper, leveled Conquest skills via catalog + stored levels.

## Changes to `stat_contributions`

1. Remove `damage_up`, `aoe_damage_up`, `attack_speed_up`, `crit_rate_up`, `heal_up` from Attack/Health flat mapping used for Conquest contribution strength **or** stop using those flats for Arena/Conquest objective once sim-lite is wired.
2. Keep `attack_up` / `defense_up` / `health_up` / `damage_taken_down` mapping only if still needed for explain UI; prefer sim-lite as the optimiser objective.
3. `_conquest_percents` must continue to include Defense/Health kinds (existing family-gate fix); sim-lite reads the same leveled percents.

## Explicit non-goals

- Tick-accurate skill rotation, stun windows, targeting priority.
- Full Monte Carlo (Radiant #38-class).
- Applying Conquest coeffs in Bear/Swordland.
- Auto-scraping all Mastery ladders in OG-01 (seed examples only).

## Testing

- Ladder resolution vs linear fallback.
- Amadeus 3-hit ultimate: SkillDPS scales with `hits=3` and ladder step.
- AoE kind multiplies by `aoe_targets`; single-target does not.
- EDT amp multiplies SkillDPS.
- Score increases when Attack Up rises with fixed coeffs.
- Formation: swapping in higher ultimate ladder level raises Conquest optimiser score.

## Calibration (OG-09)

After wiring, compare top lineups to known stage clears. Adjust `α`, `aoe_targets`, and `DefScale` only with recorded before/after notes in the backlog validation section.
