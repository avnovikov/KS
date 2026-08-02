# Formula-first gear expedition stats — design

## Goal

Gear XP spend and gear assignment scoring must derive expedition lethality/health
from **rarity + enhancement level + mastery**, not from frozen OCR percentages.
OCR remains a **sanity check** only.

## Problem

`piece_score` preferred OCR `stats.lethality` / `stats.health`. Leveling a piece
in Gear XP only updated `power`, so `gear_bonus_by_troop` (and event utility)
never changed → ΔU = 0 → no spends.

## Sources

| Tier | Base | Cap L | Max % | Formula | Source |
|------|------|-------|-------|---------|--------|
| Blue | 6% | 60 | 14.4% | `0.06 + L×0.0014` | Inventory OCR fit (L0/7/8/9) |
| Epic | 9% | 80 | 25.8% | `0.09 + L×0.0021` | kingshotoptimizer.com |
| Mythic | 15% | 100 | 50% | `0.15 + L×0.0035` | kingshotoptimizer.com |
| Red L≥100 | — | 200 | 100% | `0.50 + (L−100)×0.005` | kingshotoptimizer.com |

Mastery (mythic/red): `final = enhanced × (1 + 0.1 × mastery)`.

Grey/Green: caps 20/40 known from community guides; base/max not published —
**no formula scoring** until calibrated (power fallback only; do not invent).

Local copy: `config/hero_gear_optimizer/pieces_and_stats.yaml` (update Blue +
correct Epic slope note: per-level over cap, not `/100` for Epic).

## Behavior

1. `expedition_stat_fraction(rarity, level, mastery) -> float | None`
2. `piece_score` uses formula % when available; else power fallback
3. OCR never feeds scoring; optional `ocr_stat_delta` helper for warnings later
4. `cap_for_rarity`: blue 60, green 40, grey 20, epic 80, mythic 100, red 200

## Non-goals

- Mastery spend / forgehammers in Gear XP v1
- Special abilities / imbuement expedition milestones in scoring
- Auto-correcting OCR stores from formula

## Acceptance

- Mythic L51 M2 → 39.42% (matches known OCR)
- Epic L41 → 17.61%; Blue L0/8/9 → 6.00 / 7.12 / 7.26
- Leveling a scored piece changes `piece_score` and can yield Gear XP ΔU > 0
