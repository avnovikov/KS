# Gear inventory — manual Add piece

**Date:** 2026-08-10  
**Branch / worktree:** `feature/gear-inventory-add`  
**Status:** Approved for implementation  
**Depends on:** Gear inventory UI, `config/gear_names.yaml`, `GearStore`

## Goal

Let the player add another hero-gear piece from Inventory → Gear without OCR (e.g. a second cavalry epic gloves set). Duplicates of the same troop×slot×rarity are allowed.

## Decisions

| Topic | Choice |
|-------|--------|
| Form | **A** — troop type + slot + rarity only |
| Name | From `config/gear_names.yaml` via `canonical_gear_name` (not free text) |
| Persistence | `GearStore.upsert` → **SQL** (`gear.db`) + `gear.json` (same as OCR pieces) |
| Duplicates | Always create a new `piece_id` |
| Approach | `POST /api/gear` + toolbar Add dialog |

## API

`POST /api/gear`

Body:

```json
{ "troop_type": "cavalry", "slot": "gloves", "rarity": "epic" }
```

Server:

1. Normalize troop / slot / rarity (same helpers as PATCH).
2. Resolve `name = canonical_gear_name(...)`; **400** if the triple is unknown in YAML.
3. Allocate `piece_id = manual-{n}` where `n` is one more than the max existing `manual-*` index (or `1` if none).
4. Upsert `GearRecord` with name, troop, slot, rarity; enhancement / mastery / power `null`.
5. Return `{ "ok": true, "piece": { ... } }` including `icon_url` like `GET /api/gear`.

## UI

- Toolbar **Add** opens a small dialog: troop / slot / rarity selects + confirm.
- On success, reload the table (or insert the new row) so levels can be edited like any other piece.

## Out of scope

- Filling OCR conquest/expedition stats on add
- Bulk import / rename outside YAML
- Changing rescan behaviour

## Testing

- Unit/API: POST creates SQL+JSON row; second identical triple gets a new id; unknown triple → 400.
- Name matches `gear_names.yaml` for cavalry/gloves/epic.
