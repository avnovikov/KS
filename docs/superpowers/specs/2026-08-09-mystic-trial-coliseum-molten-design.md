# Mystic Trial rooms — Coliseum, Molten Fort, Radiant v1.1 — Design

**Date:** 2026-08-09  
**Status:** Ready for implementation planning  
**Branch / worktree:** `feature/mystic-trial-coliseum-molten`  
**Backlog:** OG-08 (Molten), GH [#37](https://github.com/avnovikov/KS/issues/37)/[#38](https://github.com/avnovikov/KS/issues/38)/[#47](https://github.com/avnovikov/KS/issues/47); Coliseum (new local story, no new GH issue required)  
**Companion:** [2026-08-09-radiant-spire-governor-design.md](2026-08-09-radiant-spire-governor-design.md), [2026-08-09-governor-skills-all-optimisers-design.md](2026-08-09-governor-skills-all-optimisers-design.md)

## Goal

Ship a **shared Mystic Trial optimiser shell**, then **Radiant Spire v1.1** (enemy floor stubs + MC/multi-round), then **Coliseum** and **Molten Fort** optimiser pages that reuse the shell with room-specific stat focus — without inventing a second governor or ratio-search stack.

## Locked product choices

| Topic | Choice |
|-------|--------|
| Architecture | Shared mystic-trial kernel (extract from Radiant); room adapters plug weighting |
| Radiant | v1.1: [#37](https://github.com/avnovikov/KS/issues/37) floors → [#38](https://github.com/avnovikov/KS/issues/38) MC |
| Molten MVP | Full slice: ratio search + page + API; **governor-primary** |
| Coliseum MVP | Full slice: ratio search + page + API; **heroes + hero gear primary** |
| Build order | Shared shell → Radiant floors/MC → Coliseum → Molten |
| Proxy | Keep `√(Σoffense × Σtough)` until floor MC available; always show proxy banner when proxy used |
| New GH issues | None — use #37/#38/#47 + docs backlog |

Community baselines (Kingshot Mastery / guides): Coliseum ~50/10/40; Molten ~60/15/25; Radiant ~50/15/35. Heroes selectable in Coliseum and Radiant; Molten is governor-gear focused (heroes light/fixed).

## Architecture

```text
config/mystic_trial/
  rooms.yaml                 # or per-room files + index
  radiant_spire_floors.yaml  # #37
  coliseum.yaml / molten_fort.yaml  # seeds, published ratios, focus

ks/heroes/optimize/mystic_trial/
  types.py / rooms.py        # RoomConfig load
  ratios.py                  # normalize, candidates, counts_for_ratio
  proxy.py                   # score_march √(off×tough)
  floors.py                  # load stubs (#37)
  combat_mc.py               # multi-round / MC (#38)
  radiant.py / coliseum.py / molten.py  # adapters (or thin wrappers)

ks/heroes/ui/
  templates + static per room
  APIs: /api/optimize/{radiant-spire,coliseum,molten-fort}
```

Refactor existing `radiant_spire.py` onto shared `ratios` + `proxy`; keep public `optimize_radiant` API stable for callers.

## Room adapters (stat focus)

| Room | Primary % stack | Heroes | Governor | Marches (v1) |
|------|-----------------|--------|----------|--------------|
| Radiant | Full account (as today) | Dual exclusive picks + gear | Included | 2 active / 3 schema |
| Coliseum | Hero expedition contribs + hero gear | March picks + gear | Off or tiny optional weight | 1 (extend later if needed) |
| Molten | `governor_troop_bonuses()` Atk%/Def% (+ sets) | Light / fixed lineup | **Required** | 1 |

Shared ratio search: room seed + published alternates + ±5% grid (same algorithm as current Radiant).

## Radiant v1.1

1. **#37 Floor stubs** — `config/mystic_trial/radiant_spire_floors.yaml`: floor id, enemy ratio (default 33/33/33; floor 10 ≈ 53/27/20), `enemy_power_scale` or unit stats. Editable; community-seeded.  
2. **#38 Combat** — multi-round or Monte Carlo vs stub; objective → estimated win rate / remaining HP. Missing floor → **proxy fallback** + warning.  
3. UI: optional floor selector on Radiant page; `?floor=` on API.

Coliseum/Molten may reuse the floor schema later; this program seeds **Radiant floors first**.

## UI / API

- Subnav: Event lineups | Gear XP | Radiant Spire | **Coliseum** | **Molten Fort** | Hero levels  
- Pages mirror Radiant (Run, banner, ratio, counts, breakdown); Radiant keeps dual-march cards.  
- JSON shape shared: `marches`, `lineup_score`, `proxy_banner`, `room`, optional `floor`, `engine` (`proxy`|`mc`).  
- Errors: missing inventory → 4xx with clear message; unknown floor → proxy + warning.

## Testing

- Unit: ratio seeds per room; Molten score moves with governor Atk%; Coliseum score moves with hero gear/expedition, not governor-primary.  
- Unit: floor load; MC path selected only when floor present.  
- UI smoke: three pages 200; Radiant floor param.

## Non-goals

- Forest of Life, Crystal Cave, Knowledge Nexus rooms  
- Charms / pets / research inventory UIs  
- ADB scrapes of trial screens  
- Stage climb planner / material upgrade optimiser  

## Phased delivery (PRs)

1. Shared shell + Radiant refactor (behavior-preserving).  
2. Radiant #37 floors + UI/API hook (proxy still default).  
3. Radiant #38 MC engine + floor selector objective.  
4. Coliseum adapter + page + API.  
5. Molten adapter + page + API; mark OG-08 Done.

## Open calibration

- Exact Molten “no hero select” vs light hero weight — default light weight from a fixed best expedition trio if UI always shows heroes; document in room YAML.  
- Whether Coliseum needs dual-march like Radiant — v1 single march; revisit after first live clear.  
- MC round count / variance knobs after first Sunday Radiant comparison.
