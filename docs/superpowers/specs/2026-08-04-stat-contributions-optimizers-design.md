# Stat contributions across Event lineups & optimisers

**Date:** 2026-08-04  
**Branch / worktree:** `feature/stat-contributions-optimizers`  
**Status:** Approved for planning  
**Depends on:** Event lineups UI, Arena/Conquest survival, Swordland/Bear recommend, Gear XP spend

## Goal

Expose and **score with** per-hero power and combat stats split into **hero / skills / gear**, using the **event-correct family** (Conquest vs Expedition). Event lineups show formation totals on cards and per-hero tables in the modal. **All optimisers** consume the same contribution totals (big-bang rewrite of scorers around this model).

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| UI placement | **C** — formation totals on cards + per-hero in detail modal |
| Stat columns | Power + family-specific stats (Conquest flats **or** Expedition %) |
| Event → family | Arena + Conquest → `conquest`; Swordland + Bear → `expedition` |
| Scope | Display **and** scoring; shared helper used by Gear XP too |
| Split method | **A** — estimate: skills from scrape; hero = naked − skills; gear from assignment |
| Delivery | **3** — rewrite every scorer around contributions in one effort |

### Event family (from public guides)

| Screen | Family | Primary stats shown / scored |
|--------|--------|------------------------------|
| Arena (attack/defense) | `conquest` | Power + Conquest flats (Hero/Escort Attack, Defense, Health, …) |
| Conquest | `conquest` | Same |
| Bear Trap | `expedition` | Power + Expedition % (Attack/Defense/Health/Lethality by troop) |
| Swordland | `expedition` | Same |

Sources: [Kingshot Conquest guide](https://kingshotmastery.com/guides/kingshot-conquest-guide), [Hero skills guide](https://kingshotmastery.com/guides/hero-skills-and-builds) — Conquest skills for Conquest + Arena; Expedition for map/rallies/Bear Hunt and similar events.

## Architecture

### Core type — `StatContribution`

For one hero (optional assigned gear) and a `family` of `conquest` | `expedition`:

```text
StatContribution
  family: conquest | expedition
  estimated: bool          # true while skill split is rule A
  skills_incomplete: bool  # missing current_bonus / skills
  power: { hero, skills, gear, total }
  stats: { <label>: { hero, skills, gear, total }, ... }
```

- **Conquest `stats` labels:** Hero Attack, Hero Defense, Hero Health, Escort Attack, Escort Defense, Escort Health (as available).
- **Expedition `stats` labels:** troop Attack / Defense / Health / Lethality percents relevant to the hero’s troop (and formation rollups may sum or average by label).

### Single module

`ks/heroes/optimize/stat_contributions.py` owns estimation. No other module invents skill/gear shares.

### Estimation rule A

1. **Skills** — from scraped skill `current_bonus` / levels, filtered by family via catalog `applies_to` (conquest vs expedition / widget rules as today’s modes already distinguish). Map bonuses onto the family stat labels and a power share where estimable.
2. **Hero** — naked scraped value − skills share; floor at 0.
3. **Gear** — sum of assigned pieces: conquest flat OCR/fields, expedition formula fractions (`expedition_stat_fraction`) and/or piece expedition maps, piece `power`.
4. **Total** — hero + skills + gear. For power, if skill power share cannot be estimated, treat skills power as 0 and hero power as full naked (document in `skills_incomplete` / flags).

### Family map (config)

Event → family lives in config (event profiles or a small shared map), not scattered in scorers:

- `arena`, `conquest` → `conquest`
- `swordland`, `beartrap` → `expedition`

## Data flow

1. Load heroes + gear + catalog.
2. Compute `StatContribution` per hero for the event family (gear=None until assignment, or provisional exclusive assignment).
3. Scorers / ILP / survival / recommend / foes read **`contribution` totals** (effective power + relevant stats) — not raw `hero.power` or ad-hoc `0.15 * gear` as the primary strength signal.
4. After final gear assignment, recompute contributions and attach to API payloads for UI.

### Optimiser rewrites (in scope)

| Surface | Change |
|---------|--------|
| `scoring.py` / `recommend.py` | Expedition path uses expedition contribution totals + existing kind weights |
| `combat_formation.py` / `arena.py` / `conquest.py` | Conquest path uses conquest contribution totals; remove provisional gear heuristic as SoT |
| `front_survival.py` / `opponent_models.py` / `survival_pipeline.py` | Toughness / foe builds use contribution-backed HP/DEF/gear health |
| `spend_xp.py` | `U(gear)` rebuilds contributions under candidate gear levels |
| `optimize_run.py` | Attach `stat_family`, `formation_totals`, per-hero `contributions` |
| `optimize_events.html` | Card: compact formation totals; modal: per-hero contribution table |

### API shape (per mode / section result)

```json
{
  "stat_family": "conquest",
  "formation_totals": {
    "power": { "hero": 0, "skills": 0, "gear": 0, "total": 0 },
    "stats": { }
  },
  "heroes": [
    {
      "name": "Howard",
      "contributions": { }
    }
  ]
}
```

(Exact nesting may follow existing `heroes` / `gear_assignment` shapes; contributions must be present when status is Optimal.)

## Edge cases

- Missing skills / `current_bonus` → skills share 0; hero = full naked; `skills_incomplete=true`.
- Missing gear stats → gear share 0 for that piece; still use piece power when known.
- Hero − skills < 0 → clamp hero to 0; keep reporting consistent with naked + gear where possible.
- No gear assignment yet → gear column 0; UI still renders the table.
- Catalog miss → power/gear from scrape; skills from scrape only.

## Testing

- Unit: contribution arithmetic; family skill filter; formation rollup.
- Golden / integration: Sword, Bear, Arena, Conquest, spend_xp each run through the contribution path.
- UI/API: `/api/optimize` includes `stat_family`, `formation_totals`, per-hero `contributions`.
- Regression: update formation tests for new inputs; assert wiring and invariants (non-negative shares, total ≈ hero+skills+gear), not frozen old score values.

## Out of scope

- Scraping the in-game “from hero / from skills / from gear” popup (follow-up to replace estimates).
- Changing event YAML mode kind weights / point scenarios.
- New visual design language beyond compact totals + modal table.

## Success criteria

1. Event lineups cards show formation-level hero/skills/gear totals for the correct family.
2. Detail modal shows the same split per hero.
3. Arena/Conquest/Swordland/Bear/Gear-XP optimisers all derive strength from `stat_contributions` totals for that family.
4. No scorer remains on naked power + heuristic gear bonus as the sole SoT.
