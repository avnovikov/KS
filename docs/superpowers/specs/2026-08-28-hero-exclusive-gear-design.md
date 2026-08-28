# Hero exclusive gear (widget level) — design

**Date:** 2026-08-28  
**Status:** implemented  
**Scope:** inventory schema, Heroes UI, event optimiser scoring

## Problem

Legendary and other catalog heroes with an **exclusive gear widget** upgrade that slot from level 1 to 10. The march skill scales linearly — e.g. Jabel’s *Greaves of Faith* grants **Defender Troops’ Lethality +15%** at level 10. The optimiser models widget effects from `hero_catalog.yaml`; without a stored widget level those effects score as **zero** until you enter levels in inventory.

## Schema

Each hero in `heroes.json` may include:

```json
"exclusive_gear": {
  "level": 4,
  "max_level": 10,
  "widget_name": "Greaves of Faith",
  "widget_type": "defense",
  "source": "manual",
  "updated_at": "2026-08-28T10:00:00+00:00"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `level` | int 1–10 | Absent or cleared = no widget bonus in optimiser |
| `max_level` | int | Default 10 |
| `widget_name` | str | Filled from catalog on save when known |
| `widget_type` | str | `attack` / `defense` from catalog |
| `source` | str | `manual` for UI edits |
| `updated_at` | ISO8601 | Set on manual update |

OCR rescans **preserve** `exclusive_gear` when the incoming hero record omits it (preserve-if-absent — not pinned like hero `level`).

**Breaking change:** heroes without a stored widget level score **zero** widget effect and priority bonus. Enter levels in inventory after upgrading exclusive gear.

## Optimiser scaling

For catalog effect tags with `applies_to: widget`:

```
effective = max_value × (level / max_level)
```

Expedition skills continue to use the existing star/pellet progress factor; widget tags never use stars.

**Widget priority bonus** (garrison/rally flat bonus from catalog priorities) scales by the same factor so a level-4 defense widget is not scored like a maxed widget.

### Example: Jabel (lethality +15% at L10)

| Widget Lv | Defender lethality bonus |
|-----------|-------------------------|
| 1 | 1.5% |
| 2 | 3.0% |
| 3 | 4.5% |
| 4 | **6.0%** |
| 5 | 7.5% |
| 6 | 9.0% |
| 7 | 10.5% |
| 8 | 12.0% |
| 9 | 13.5% |
| 10 | 15.0% |

## UI

- **Inventory · Heroes:** editable **Widget Lv** column (0–10) for heroes with a catalog widget; auto-save via `PATCH /api/heroes/{name}` with `widget_level`.
- **Hero detail modal:** shows exclusive gear name, type, and level (effective % appears in optimiser why-cards).
- **Optimiser why-cards:** mention widget level and effective % when set.

## API

`PATCH /api/heroes/{name}` accepts `widget_level` (integer 0–10 or JSON `null` to clear). Rejects positive levels for heroes without a catalog widget. Non-integer values (e.g. `4.7`) return 400.

## References

- `config/hero_catalog.yaml` — widget names, march skills, `applies_to: widget` tags
- `ks/heroes/exclusive_gear.py` — scaling helpers
- `ks/heroes/optimize/scoring.py` — strength integration
