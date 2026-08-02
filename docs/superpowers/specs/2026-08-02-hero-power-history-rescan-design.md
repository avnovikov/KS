# Hero Power History on Total Rescan — design

**Date:** 2026-08-02  
**Status:** Approved in brainstorm  
**Branch:** `feature/hero-power-history-rescan`

## Goal

On **total heroes rescan** (ADB roster walk), also open Power-`i` and record force components into a **lifetime observation log** per hero, so later stories can fit **shared game curves** and predict upgrade value.

## In scope

- During live `scrape_hero` / `collect_heroes` / UI “Rescan from OCR”: tap Power-`i`, OCR Level / Stars / Skills / Gear
- Append a point under the collect dir when covariates or buckets **differ** from the last point for that hero
- Point fields: `ts`, `level`, `stars`, `pellets`, `skills` (slot→level), `P_level`, `P_stars`, `P_skills`, `gear`, `hero_power`, `sum_ok`

## Out of scope (separate stories)

- Who shares which curve / clustering
- Fitting shared game tables
- Optimiser consumption of deltas
- UI start/stop/restart of hung ADB jobs

## Storage

`{heroes_collect_dir}/power_history/{HeroSlug}.yaml`

```yaml
hero: Jabel
points:
  - scraped_at: ...
    level: 57
    stars: 3
    pellets: 1
    skills: [{slot: 0, level: 5}, ...]
    from_level: 106500
    from_stars: 226200
    from_skills: 34650
    gear_strength: 248070
    hero_power: 615420
    sum_ok: true
```

Append-only; no curve merge in this story.

## Dedup rule

Skip append when last point has the same  
`(level, stars, pellets, skill levels, from_level, from_stars, from_skills, gear_strength, hero_power)`.

## Failure mode

Power-`i` OCR failure must not abort the roster rescan; log a warning and continue.
