# Hero Gear Optimizer reference data

Copied from [Kingshot Optimizer](https://kingshotoptimizer.com/) v1.12.4 (2026-08-01) for local planning.

## Files

| File | Contents |
|------|----------|
| `build_profiles.yaml` | Stat weights (Growth / Combat / Gen4 / Unweighted) |
| `enhancement_xp_costs.yaml` | Full XP ladder 0–200 |
| `forgehammer_costs.yaml` | Mastery 0–20 hammers + mythic costs |
| `pieces_and_stats.yaml` | Piece IDs, base/max stats, fodder XP, formulas, `stat_tiers` |
| `imbuement_costs_and_bonuses.yaml` | Red milestones, costs, Expedition vs Conquest bonuses |

## Expedition stat formula (scoring)

Scoring uses **rarity + enhancement + mastery** only (OCR is sanity-check):

- Blue: `0.06 + L/60 × 0.084` (cap 60) — inventory-calibrated
- Epic: `0.09 + L/80 × 0.168` (cap 80) — kingshotoptimizer.com
- Mythic: `0.15 + L/100 × 0.35` (cap 100)
- Red L>100: `0.50 + (L−100)×0.005`
- Mastery: `× (1 + 0.1×mastery)`

Grey/Green base–max not calibrated yet — power fallback only.

## How we should use this (early + Arena/Conquest)

1. **Profile:** use `early_game_combat` (not default Growth). Higher cavalry lethality for PvP/Arena.
2. **Set model:** still one transferable set per troop type (12 pieces) first; outfit top 5 with mythic shells when possible, but dump scarce XP/hammers into the combat-weighted pieces.
3. **Priority order inside the set (combat weights):** Infantry Health (1.5) → Archer Lethality (1.3) → Cavalry Lethality (1.2) → Infantry Lethality (0.7) → Archer Health (0.6) → Cavalry Health (0.4).
4. **Do not blindly follow their “skip R140/R180”:** those are Conquest/hero-wide buffs. For Arena/Conquest they matter; for Expedition-only they don’t.
5. **Early stage:** mythic + enhancement/mastery on high-weight pieces ≫ rushing red. Their own FAQ: delay red if weighted stat/resource is poor; F2P first red stop ≈ level 120.

## Attribution

Not affiliated with Century Games. Data compiled by Kingshot Optimizer; kept here for offline optimization planning only.
