# Gear Level Lock, Consumed Delete & Grey OCR — Design

**Date:** 2026-08-02  
**Feature branch:** feature/heroes-gear-ui

---

## Problem

1. **Level lock regression.** After a full gear rescan, manually-verified enhancement and mastery levels are silently overwritten by OCR values that are often `None` for grey/common pieces (no visible badge). Users lose work.

2. **No consumed flow.** When a gear piece is used as fodder, it disappears from the physical inventory but remains as a stale record in `gear.json`. There is no way to remove it from the UI.

3. **Opaque rescan.** The POST `/api/gear/rescan` endpoint blocks until completion and returns a JSON dump. Users get no feedback during a multi-minute OCR scan.

4. **Grey-rarity OCR gaps.** Grey/common pieces lack the coloured rarity badge. Existing parsers skip them silently; no power curve existed for grey either.

---

## Decisions

### A. Merge semantics in GearStore

| Constant | Meaning |
|---|---|
| `_PRESERVE_IF_NONE` | If incoming field is `None`, keep the prior value. |
| `_LOCKED_UNLESS_OVERWRITE` | Fields (`enhancement_level`, `mastery_level`) **always** restored from prior record unless `overwrite` frozenset contains the field. |

`upsert(piece, overwrite=None) -> GearRecord` merges via `_merge_preserved` before writing.  
`get(piece_id) -> GearRecord | None` exposes in-memory lookup.  
`delete(piece_id) -> bool` removes from memory, JSON, and SQLite.

### B. Rescan: no wipe, incremental merge, stale cleanup

`rescan_gear_from_ocr` no longer calls `store.clear()`. It:
1. Wipes `details/` and `icons/` directories (screenshots, not records).
2. Collects via ADB OCR; each `store.upsert(piece)` merges locked levels.
3. After collection, deletes any `piece_id` not in the collected set.

### C. SSE streaming for rescan

`POST /api/gear/rescan` returns `text/event-stream` (SSE). Events:

| Event | Payload |
|---|---|
| `piece` | `{piece_id, name, power, enhancement_level, mastery_level, rarity}` |
| `kept` | Same fields — locked level(s) were preserved from prior record |
| `duplicate` | `{piece_id, key}` — dedupe skip |
| `done` | `{count, cache_bust}` |
| `error` | `{detail}` |

`POST /api/heroes/rescan` converted to SSE with events: `hero`, `duplicate`, `rematch`, `stopped`, `done`, `error`.

### D. DELETE /api/gear/{piece_id}

Removes the piece from store (memory, JSON, SQLite). Returns `{ok: true, deleted: piece_id}`.  
Frontend: "✕" (consume) button per row triggers a confirm dialog then `DELETE` fetch; row removed on success.

### E. Power curves extended

`_RARITY_LINEAR` gains `grey`/`gray`/`common`/`white`: intercept=4500, slope=168 (calibrated from scans).  
`rarity_power_curves(max_enhancement=80) -> dict[str, list[float]]` returns mastery-0 power arrays for `grey/green/blue/epic/mythic` for live client-side power estimation.

### F. Grey OCR improvements in gear_parse.py

- `_SKIP_NAME` extended with expedition/conquest stat labels (e.g. "Hero Attack") that OCR surfaces as names for grey pieces.
- `_KNOWN_GEAR_NAMES` extended: `Guardian's Helm`, `Stonewall Helm`, `Warrior's Shroud/Greaves`, `Cuirassier's Armet`.
- `_KNOWN_GEAR_FUZZY` maps OCR fragments like "Ston ll Hel" → Stonewall Helm.
- `_reject_power_prefix_badges(plus_vals, power)` filters `+N` tokens whose digit count equals/exceeds the power digit count.
- `_infer_rarity_from_power(power, mastery)` fits power against all known curves; used when `_parse_rarity` returns `None` (score = err + 15×enhancement to prefer low-rarity interpretations).
- `_parse_name` slot-hint ranking: candidates containing a slot keyword (helm, boots, …) sorted first.

### G. Heroes collector: power-aware duplicate detection

`collect_heroes` gains:
- `on_progress(event, payload)` callback.
- `max_consecutive_duplicates=3` — breaks the cell loop after N same-name+same-power hits in a row.
- `rematch_name_fn` hook — called with `(hero, exclude_names=seen)` on same-name+different-power to re-identify the hero.

### H. config/gear.yaml

- `max_pages: 3` — supports larger inventories.
- 6th row of cells at `y=1720` (four cells) — catches grey pieces at the bottom of a taller backpack.

---

## Non-goals

- No change to the optimize/events/XP UI endpoints.
- No automatic cleanup of hero records from the heroes store after rescan.
