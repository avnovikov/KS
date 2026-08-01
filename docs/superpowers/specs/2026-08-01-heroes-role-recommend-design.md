# Heroes Role Recommend Engine Design

**Date:** 2026-08-01  
**Status:** Approved for implementation  
**Workspace:** `.worktrees/feature-heroes-collector`  
**Branch:** `feature/heroes-collector`

## Goal

Given a scraped owned roster (`HeroRecord`s) and manual troop inventory, recommend the **role/mode**, **3-hero lineup**, and **troop formation** that maximize **expected personal Relic Points** for a single march (Swordland-style scoring).

## Locked decisions

| Topic | Decision |
|-------|----------|
| Approach | ILP / integer linear program (PuLP + CBC) |
| Role | Engine **chooses** role/mode to max E[personal points]; optional `--force-role` override |
| Scope | One march at a time (multi-march later) |
| Roster input | `heroes.json` / SQLite from collector |
| Catalog | Hybrid: KingshotPro cache (gen, troop, role tiers) + local YAML (widget_type, expedition effect tags) |
| Troops | Manual `config/troops.yaml` |
| Capacity | Manual `march_capacity` + escort bonus from selected `HeroRecord`s when present |
| Objective | Expected **personal** Relic Points (not alliance points, not raw combat power) |
| Combat model | Linear strength proxy → expected combat points (no full battle sim in v1) |

## Modes evaluated

For each mode, solve the ILP under that mode’s constraints + scenario priors; pick the mode with highest `E[personal_points]`.

| Mode | Typical channels |
|------|------------------|
| `garrison` | Occupation drip + defend combat (40 pts / 10k enemy power) |
| `rally_lead` | Attack combat (80 / 10k) + first-control share |
| `joiner` | Loot/crates + undercellars + limited combat via join |
| `solo` | Attack combat; widgets ignored |

## Architecture

```
ks/heroes/optimize/
  catalog.py       # KingshotPro cache + hero_catalog.yaml join
  scenarios.py     # load point_scenarios.yaml
  scoring.py       # per-hero linear strength / effect scores
  model.py         # build + solve ILP for one mode
  recommend.py     # evaluate all modes → best + alternatives
```

CLI: `ks-heroes recommend --heroes … --troops … [--force-role …]`

## ILP (per mode)

**Vars:** `x_h ∈ {0,1}` (hero selected); `t_I, t_C, t_A ∈ ℤ≥0`.

**Constraints:**
- `∑ x_h = 3`
- `t_I + t_C + t_A ≤ march_capacity + ∑ x_h · escort_h`
- `t_k ≤ owned_k`
- Optional: at most one hero per troop type (default on)
- Mode filters: e.g. `rally_lead` requires ≥1 attack-widget hero; `garrison` ≥1 defense-widget

**Objective:** maximize E[personal points] = sum of active channels for the mode’s scenario:

- Combat: `rate/10000 × expected_enemy_power_killed(strength)`
- Occupation: `minutes_held × personal_rate`
- First control: `p_first × personal_bonus`
- Loot/gather: scenario priors × strength/capacity factors

Strength is linear in selected heroes’ catalog effect tags × instance skill levels/stars + troop counts weighted by formation utilities for kingdom gen.

## Data files

| Path | Role |
|------|------|
| `config/troops.yaml` | owned I/C/A, `march_capacity` |
| `config/hero_catalog.yaml` | widget_type, effect tags / coeffs per hero |
| `config/point_scenarios.yaml` | priors per mode |
| `artifacts/heroes/catalog_cache/kingshotpro_heroes.json` | cached open dataset |
| `artifacts/heroes/recommend_result.json` | last recommendation |

## Output contract

```json
{
  "recommended_mode": "garrison",
  "heroes": [{"name": "Zoe", "reason": "..."}],
  "troops": {"infantry": 90000, "cavalry": 22500, "archers": 37500},
  "ratios": {"infantry": 0.6, "cavalry": 0.15, "archers": 0.25},
  "effective_capacity": 150000,
  "expected_personal_points": 12345.0,
  "breakdown": {"occupation": 8000, "combat": 4345},
  "alternatives": [{"mode": "rally_lead", "expected_personal_points": 11000}]
}
```

## Catalog + event weights

- `config/hero_catalog.yaml` — widget type/name/march skill, Mastery priority stars, first-expedition `effect_op` (101/102/111/…)
- `config/events/swordland.yaml` — mode-specific kind weights + `effect_op` multipliers for Swordland
- CLI: `ks-heroes recommend … --event config/events/swordland.yaml` (default)

## Out of scope (v1)

- Multi-march troop pool split
- Live ADB in recommend path
- Exclusive gear scrape / full nonlinear combat sim
- Alliance Relic Points optimization

## Testing

- Fake roster fixtures: defense-heavy roster prefers `garrison`; attack-widget roster prefers `rally_lead` under equal scenarios tuned for that
- Capacity and ownership constraints bind
- `--force-role` restricts to that mode
