# Radiant Spire — opponent AI heroes + gold gear (pre-MC)

**Date:** 2026-08-09  
**Branch:** `feature/radiant-floor-selector`  
**Status:** Implemented  
**Depends on:** stage·round opponent persistence  
(`2026-08-09-radiant-stage-round-opponents-design.md`)

## Goal

Before a real multi-round MC engine, make win rate react to **saved opponents**:
pick **3 catalog heroes**, one shared **hero level**, one shared **mythic/gold gear
enhancement**, plus existing troop counts/levels/bonuses. Score the enemy with
the same proxy math as the player and duel the two proxies.

## Decisions

| Topic | Choice |
|-------|--------|
| Heroes | 3 named catalog picks per opponent march |
| Levels | One shared hero level + one shared gear enhancement for the march |
| Gear | Preset **mythic** 4-piece set per hero, troop-matched, all at that enhancement |
| Scoring | Symmetric `score_march` (+ hero atk/def/leth/hp from contributions with synthetic gear) |
| Win rate | `adj_player / (adj_player + enemy)` using real enemy proxy (not `player × power_scale`) when opponent data is complete enough |
| Fallback | Incomplete opponent (no heroes / no troop counts) → legacy `enemy_power_scale` stub + warning |
| Persist | Extend stage·round·slot YAML; Apply / Copy include heroes + levels |

## Data (march record addition)

```yaml
marches:
  - hero_names: [Helga, Jabel, Diana]
    hero_level: 80
    gear_enhancement: 80
    levels: {infantry: 6, cavalry: 6, archers: 6}
    counts: {infantry: 50000, cavalry: 50000, archers: 50000}
    bonuses: { ... }
```

## Engine

1. Build synthetic `GearRecord` mythic pieces (4 slots × troop) at `gear_enhancement`.
2. Build lightweight `HeroRecord`s for the three names at `hero_level` (stars/pellets defaults; expedition stats from catalog contribution path as today).
3. `score_march` with enemy counts, unit stats for enemy troop levels, and atk/def/leth/hp % from hero shares + stored bonuses.
4. `simulate_floor(player, stub, enemy=enemy_score)` — when `enemy` present, use it; else scale stub.

## UI

On selected opponent: 3 hero selects (catalog), Hero level, Gold gear +, existing troops/bonuses, Apply / Copy.

## Out of scope

Multi-round sampled MC, OCR foe boards, per-hero different levels, charms/pets.
