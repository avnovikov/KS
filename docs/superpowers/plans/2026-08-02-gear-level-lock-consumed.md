# Plan: Gear Level Lock, Consumed Delete & Grey OCR

**Date:** 2026-08-02  
**Branch:** feature/heroes-gear-ui  
**Spec:** `docs/superpowers/specs/2026-08-02-gear-level-lock-consumed-design.md`

---

## Tasks

- [x] **A** `ks/heroes/gear_store.py` — add `_PRESERVE_IF_NONE`, `_LOCKED_UNLESS_OVERWRITE`, `_merge_preserved`, update `upsert(overwrite=)`, add `get()`, `delete()`
- [x] **B** `ks/heroes/gear_collector.py` — add `on_progress` callback; emit `piece`/`kept`/`duplicate` events
- [x] **C** `ks/heroes/ui/rescan.py` — remove `store.clear()`, pass `on_progress`, delete stale piece_ids post-collect
- [x] **D** `ks/heroes/ui/app.py` — `update_piece_levels` uses `overwrite`; gear rescan → SSE; `DELETE /api/gear/{piece_id}`; `gear_page` supplies `power_curves_json`; heroes rescan → SSE
- [x] **E** `ks/heroes/collector.py` — `on_progress`, `max_consecutive_duplicates=3`, `_same_power`, `_rematch_hero_name`
- [x] **F** `ks/heroes/ui/power.py` — grey curve; `rarity_power_curves()`
- [x] **G** `ks/heroes/gear_parse.py` — grey OCR helpers: `_reject_power_prefix_badges`, `_infer_rarity_from_power`, fuzzy names, slot-hint ranking, extended `_SKIP_NAME`
- [x] **H** `config/gear.yaml` — `max_pages: 3`, 6th row cells at y=1720
- [x] **I** `ks/heroes/ui/templates/gear.html` — `#rescan-log` SSE log, consume `✕` button, live power, grey CSS
- [x] **J** `ks/heroes/ui/templates/heroes.html` — `#rescan-log` SSE log, rematch/stopped events
- [x] **K** `ks/heroes/ui/heroes_rescan.py` — forward `on_progress` to `collect_heroes`

## Tests

- [x] `tests/test_gear_store.py` — lock preserve, delete, merge semantics
- [x] `tests/test_heroes_gear_ui.py` — SSE rescan, DELETE, level preserve, enhancement overwrites stale power
- [x] `tests/test_gear_parse.py` — grey Guardian's Helm, Stonewall fuzzy, _infer_rarity_from_power
- [x] `tests/test_heroes_cli.py` — grid cells: 24
- [x] `tests/test_gear_collector.py` — on_progress piece/kept/duplicate events
- [x] `tests/test_heroes_collector.py` — 3-dup stop, rematch
