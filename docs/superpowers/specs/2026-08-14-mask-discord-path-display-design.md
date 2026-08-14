# Mask Discord user id in UI path display

**Date:** 2026-08-14  
**Issue:** #60  
**Branch:** `feature/mask-discord-path-display`

## Goal

Do not show full Discord snowflake ids in Inventory/Optimiser page-meta paths (`…/users/<id>/…`).

## Approach

- Helper `mask_discord_id_in_path` → `146***2142`
- Apply via `mask_path_fields` in `_shell_page` for `*_dir` / `troops_path`
- Filesystem paths unchanged

## Tests

`tests/test_path_display_mask.py`
