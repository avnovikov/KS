# Radiant Spire opponent panel (battle-report bonuses)

**Date:** 2026-08-09  
**Branch:** `feature/radiant-floor-selector`  
**Status:** Approved for implementation (“lets try”)

## Goal

When a Radiant floor is selected, show an **Opponent** section with two marches mirroring the player layout: troop mix breakdown plus per-troop **Attack% / Defense% / Lethality% / Health%** from battle report / in-game opponent screen. No invented enemy heroes or levels.

## Decisions

| Topic | Choice |
|-------|--------|
| Heroes | Layout-only `AI` placeholders (not roster heroes) |
| Bonuses | Per troop type: `attack_pct`, `defense_pct`, `lethality_pct`, `health_pct` |
| Source | YAML defaults + **editable UI** (Apply → query overrides); optional YAML paste |
| Scoring | Ratio overrides affect MC mix; bonuses still **display only** |
| Proxy-only | Hide opponent panel when no floor stub |
| Layout | Opponent **above** your lineup |

## Data

Extend `config/mystic_trial/radiant_spire_floors.yaml`:

```yaml
floors:
  10:
    enemy_ratio: {infantry: 0.53, cavalry: 0.27, archers: 0.20}
    enemy_power_scale: 2.0
    enemy_bonuses:
      infantry:  { attack_pct: 0, defense_pct: 0, lethality_pct: 0, health_pct: 0 }
      cavalry:   { attack_pct: 0, defense_pct: 0, lethality_pct: 0, health_pct: 0 }
      archers:   { attack_pct: 0, defense_pct: 0, lethality_pct: 0, health_pct: 0 }
```

Missing `enemy_bonuses` → zeros (UI shows 0.0%; fill later from reports).

## API / UI

- `RadiantResult.opponent`: `{ marches: [...], bonuses: {...} }` when floor stub present.
- Each opponent march: `hero_names: ["AI","AI","AI"]`, `ratio`, `counts` (enemy ratio × player march filled size), `bonuses`.
- UI: **Opponent section on top** with editable I%/C%/A% and Atk/Def/Leth/HP% inputs + Apply.
- Query overrides: `enemy_infantry` / `enemy_cavalry` / `enemy_archers` (percents or fractions), `enemy_bonuses` (JSON).

## Out of scope

OCR of battle reports, Events foe boards, wiring bonuses into MC win_rate.
