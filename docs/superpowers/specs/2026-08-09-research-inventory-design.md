# Research inventory (Academy Battle %)

**Issue:** [#53](https://github.com/avnovikov/KS/issues/53)  
**Date:** 2026-08-09

## Problem

Radiant (and other expedition proxies) understate formation Attack/Lethality/… vs in-game battle reports because **Academy / War Academy research** is not in inventory. Battle-report paste already captures the full stack, but we need an editable research layer for day-to-day optimisation without re-pasting every fight.

## Decision

1. **Store:** `data/research/<run>/research.yaml` — per troop (`infantry` / `cavalry` / `archers`) percent-points for `attack_pct`, `defense_pct`, `lethality_pct`, `health_pct` (same units as governor / expedition hero shares).
2. **UI:** Inventory → Research — manual table + note; GET/PUT `/api/research`.
3. **Scoring:** `optimize_radiant` adds research into march `atk_pct` / `def_pct` / `leth_pct` / `hp_pct` alongside heroes + governor.
4. **No double-count:** when a future (or existing) battle-report override replaces the formation stack, research is not stacked on top of that override. On this branch of main, Radiant has no report override yet — research always adds to heroes+governor until that lands.

## Non-goals

- ADB OCR of Academy screens
- Charms / pets / skins
- Auto-summing every tree node from a dump (user sums or pastes totals)

## How to fill from the game

1. City → Academy → **Battle** tree (and War Academy Truegold trees if owned).
2. Sum current levels for Infantry/Cavalry/Archer Attack, Defense, Lethality, Health.
3. Enter those totals as percent-points (e.g. `22.5` for +22.5%), or paste a battle report’s formation totals into Radiant player bonuses when that UI exists and leave research at 0 to avoid double-count.
