# Radiant Spire — stage · round opponents (save & reuse)

**Date:** 2026-08-09  
**Branch:** `feature/radiant-floor-selector`  
**Status:** Implemented (2026-08-09)  
**Supersedes (partial):** floor-only selector + I%/C%/A% overrides in
`2026-08-09-radiant-opponent-panel-design.md` — opponent **heroes** remain AI
placeholders; bonuses remain display-only for MC.

## Goal

Let the player record real Radiant Spire foes as **stage · round** opponent
marches (troop **level + headcount** + battle-report bonuses), **persist them
automatically on Apply**, and reload the same record whenever that stage·round
is selected again.

## Decisions

| Topic | Choice |
|-------|--------|
| Naming | **Stage** and **Round** (not “floor”) in UI copy and APIs going forward |
| Identity | Key = `(stage, round)` plus march slot `0` / `1` (two opponent marches) |
| Persist | **Automatic on Apply** (no separate Save) |
| Apply target | Selected **Opponent** chip only; if none selected → error *Select an opponent march below, then Apply* |
| Troop inputs | Per type: integer **level** 1–11 + non-negative integer **count** |
| Bonuses | Per type: Atk% / Def% / Leth% / HP% (display; still not in MC win_rate) |
| Storage | Separate user file (not git config stubs) — see Data |
| Difficulty stubs | Keep `config/mystic_trial/radiant_spire_floors.yaml` for `enemy_power_scale` (and optional default ratio); look up by **stage** for now (round ignored for scale unless we later add stage·round scales) |
| Proxy-only | Stage or round blank / unset → no opponent panel, proxy scoring only |
| Reuse | Selecting a saved stage·round loads stored marches into the panel and board |

## Data

### User opponents (owned by UI)

Path (default): under the heroes/governor data root the UI already uses, e.g.

`{data_root}/mystic_trial/radiant_opponents.yaml`

or, if no dedicated data root is configured, beside governor:

`{governor_dir}/mystic_trial/radiant_opponents.yaml`

Shape:

```yaml
version: 1
stages:
  "3":
    "2":                    # stage 3 · round 2
      marches:
        - levels: {infantry: 6, cavalry: 6, archers: 6}
          counts: {infantry: 42000, cavalry: 18000, archers: 15000}
          bonuses:
            infantry:  { attack_pct: 120, defense_pct: 80, lethality_pct: 90, health_pct: 70 }
            cavalry:   { attack_pct: 0, defense_pct: 0, lethality_pct: 0, health_pct: 0 }
            archers:   { attack_pct: 0, defense_pct: 0, lethality_pct: 0, health_pct: 0 }
        - levels: {infantry: 6, cavalry: 6, archers: 6}
          counts: {infantry: 40000, cavalry: 20000, archers: 16000}
          bonuses: { ... }
```

- Missing stage·round → build opponent panel from stub ratio × player march size (today’s behaviour) with default level 6.
- Apply on march slot `i` upserts only that slot; the other slot is left as-is (create empty/default second slot if needed so the file always has two entries when first saved).

### Config stubs (repo)

`config/mystic_trial/radiant_spire_floors.yaml` remains the difficulty table.
UI/API rename query `floor` → `stage` (accept `floor` as deprecated alias for one release). Round is **not** required for stub lookup in v1.

## API / UI

### Query / optimize

- `GET /api/optimize/radiant-spire?stage=&round=`
- When both set: load stub by stage; merge saved opponents for that stage·round into `opponent.marches` (counts, levels, bonuses, derived ratio).
- Derived ratio from counts feeds existing MC mix override (same as today’s enemy_* ratio query).
- Optional: stop requiring ad-hoc `enemy_infantry` query once persistence owns the ratio.

### Persist

- `PUT /api/mystic-trial/radiant-opponents/{stage}/{round}/{slot}`  
  body: `{ levels, counts, bonuses }`  
  or a single `PUT .../radiant-opponents` with stage, round, slot in JSON.
- Called by the page **on Apply** (after validation), then re-fetch optimize.

### UI chrome

- Title row: **Stage** `[number]` · **Round** `[number]` (replace Floor select).
- Opponent overrides panel: level + count per troop; bonuses; **Apply**.
- Mode chips: March 1/2 and Opponent 1/2; Apply edits the selected Opponent chip’s stored slot.
- Board: show T-level · count chips on opponent marches (already sketched).

## Out of scope

- OCR of battle reports.
- Wiring bonuses into MC `win_rate`.
- Named free-library opponents unrelated to stage·round.
- Per-round difficulty scales in config (can follow later).
- Renaming the git branch / every historic “floor” symbol in tests in one go — prefer API `stage` + thin alias.

## Acceptance

1. Enter stage 3 · round 2, select Opponent 1, set levels/counts/bonuses, Apply → file contains that slot; reload page / re-select same stage·round → values return.
2. Apply with March (you) selected → error asking to select an opponent.
3. Blank stage or round → proxy-only, no opponent panel.
4. Second opponent march can be saved independently under the same stage·round.
