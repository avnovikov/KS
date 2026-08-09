# Hero catalog skills + editable levels (popup)

**Date:** 2026-08-09  
**Branch / worktree:** `feature/hero-skill-levels-popup` → `.worktrees/feature-hero-skill-levels-popup`  
**Status:** Approved for implementation  

## Goal

Let players set each hero’s skill levels (1–5) in the Inventory · Heroes detail popup, using **skill names from the public catalog** (kingshotmastery.com), overwriting OCR skill rows. Optimisers must honor those levels.

## Decisions (locked)

| Topic | Choice |
|--------|--------|
| Skill list source | Catalog (`hero_catalog.yaml`), seeded from kingshotmastery.com hero pages |
| OCR levels | Edits **overwrite** `HeroRecord.skills[]` (no separate override layer) |
| Level range | **1–5** |
| Optimiser impact | **Yes** — all optimisers via contribution / skill percent path |
| UI layout | Skills in the popup in **2 columns** |
| Scoring model | `(level / 5) × effect max_value` when skill has `effect_kind`; else keep existing scrape/`current_bonus` / star-scaled fallback for unlinked effects |

## Catalog shape

Per hero under `heroes.<Name>`:

```yaml
skills:
  - slot: 0
    name: Burst Fire
    family: conquest
  - slot: 1
    name: Defense Upgrade
    family: conquest
  - slot: 2
    name: Weapon Upgrade
    family: conquest
  - slot: 3
    name: Stand of Arms
    family: expedition
    effect_kind: lethality_up
  - slot: 4
    name: Shield Wall
    family: expedition
    effect_kind: damage_taken_down
```

- Epic: typically 3 conquest + 2 expedition.  
- Mythic: typically 3 conquest + 3 expedition (widgets out of scope for v1 level controls unless already in OCR slots).  
- `effect_kind` links expedition (and conquest where useful) skills to existing `effects[].kind` for scoring.  
- Cite source URL / extracted_on in catalog header or per-batch script notes.

## Persistence

- `PATCH /api/heroes/{name}/skills` (or extend existing hero PATCH) body: `{ skills: [{ slot, name, level }, ...] }`.  
- Store writes full `skills` tuple onto the hero, replacing previous OCR rows for those slots.  
- Unset level not allowed in UI (always 1–5 once saved); first open may show empty until user sets.

## UI

- Extend existing hero detail sheet (`hero_detail.js` + modal).  
- Load catalog skills for the hero + current store levels.  
- **2-column grid** of skill cards: name, family chip, level, − / +.  
- Autosave or explicit Save (prefer per-click save like governor upgrade / troops autosave pattern — save on each +/-).

## Scoring change

In `skill_effects` / `family_percents`:

1. If store skills have levels and catalog maps `effect_kind`, sum `(level/5)*max_value` for that kind (from catalog effects).  
2. Else prefer scraped `current_bonus` when present.  
3. Else star-scaled `catalog_percents` for remaining kinds.

This fixes Radiant ranking when OCR bonuses/levels are empty.

## Seeding scope (v1)

- Script or one-shot fetch for heroes present in `data/heroes/full-run` (and any catalog hero we touch).  
- Remaining catalog heroes can be filled in a follow-up pass with the same script.

## Out of scope

- Full per-level upgrade-preview tables (exact % at each step beyond linear level/5).  
- Widget skills as separate editable rows (unless already needed for completeness of names).  
- ADB skill re-scrape.  
- Frozen OCR snapshot / reset-to-OCR.

## Tests

- Catalog load: skills list for a seeded hero.  
- Store/API: PATCH overwrites skill levels 1–5.  
- Scoring: level 5 matches max_value; level 1 is 1/5.  
- UI smoke: detail popup contains 2-column skills grid and +/- controls.

## Self-review

- No placeholders left.  
- Compatible with radiant branch base.  
- 2-column UI called out.  
- Internet seed source explicit (kingshotmastery).
