# Heroes inventory — manual Add hero

**Date:** 2026-08-14  
**Branch / worktree:** `feature/heroes-inventory-add`  
**Status:** Approved  
**Depends on:** Heroes inventory UI, `config/hero_catalog.yaml` / `load_name_catalog`, `HeroStore`

## Goal

Let the player add a hero from Inventory → Heroes without OCR, picking from the catalog (same idea as gear **Add piece**).

## Decisions

| Topic | Choice |
|-------|--------|
| Form | Catalog **name** select; troop + rarity shown from catalog (read-only) |
| Catalog | `load_name_catalog()` (`hero_catalog.yaml` + optional pro cache) |
| Persistence | `HeroStore.upsert` → SQL + `heroes.json` |
| Duplicates | **Reject** if name already in roster (400) |
| Levels | level / stars / pellets / power left `null` (edit after) |
| Approach | `POST /api/heroes` + toolbar Add dialog |

## API

`POST /api/heroes`

Body:

```json
{ "name": "Helga" }
```

Server:

1. Resolve name against catalog (case-insensitive match → canonical catalog key).
2. **400** if unknown.
3. **400** if already in `HeroStore`.
4. Upsert `HeroRecord` with catalog `troop` / `rarity`; other fields null.
5. Return `{ "ok": true, "hero": { ... } }`.

## UI

- Toolbar **Add hero** opens dialog: name `<select>` (catalog minus already owned) + confirm.
- On success, toast + reload table.

## Out of scope

- Free-text names
- Skills / OCR on add
- Changing rescan behaviour

## Testing

- Unit: create persists JSON+SQL; duplicate → error; unknown → error.
- API: POST success + 400 cases; page includes add control.
