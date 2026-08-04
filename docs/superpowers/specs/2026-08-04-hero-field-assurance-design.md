# Hero field assurance levels — design

**Date:** 2026-08-04  
**Status:** Approved  
**Branch:** `bug/power-i-naked-authoritative` (heroes collector / Power-i worktree)

## Goal

Attach a durable **high / medium / low** assurance estimate (plus short reason) to every hero progression number we care about, so the inventory UI can paint **low = red**, **medium = amber**, **high = quiet**, and so manual naked-power fixes can be confirmed as **high**.

Identical naked powers across different heroes are allowed and do **not** lower assurance.

## Scope

**In scope (heroes only):**

- Stored fields: `power`, `stars`, `level`, `pellets`
- Power-i buckets when captured: `from_level`, `from_stars`, `from_skills`, `gear_strength`
- Persist assurance on `HeroRecord`
- Heroes inventory UI: cell tint + editable naked **power**
- Source ladder for collector and PATCH

**Out of scope:**

- Gear assurance
- Optimizer hard-gating on low assurance
- New Power-i bucket columns on the roster table (detail later is fine)

## Data model

On each `HeroRecord`:

```text
assurance: {
  <field>: { level: "high" | "medium" | "low", reason: string }
}
```

Fields that may appear: `power`, `stars`, `level`, `pellets`, `from_level`, `from_stars`, `from_skills`, `gear_strength`.

Rules:

- Every field that has a stored value **should** have an assurance entry.
- Missing value → no assurance required for that key.
- Round-trip through JSON store and SQLite.
- Unknown level/reason on load → treat as **medium** / do not crash.
- Present value with missing assurance key → behave as migration: **medium** / `legacy_unscored`.
- Existing `power_attention` remains the collector blocking/soft flag; when it is set, `power` (and conflicting buckets) are **low** with that reason for UI paint. Assurance is what cells use; attention can still drive row incomplete.

Migration for rows without assurance: **medium** / `legacy_unscored` (do not flash the whole roster red).

## Source ladder

| Source | Level | Reason (examples) |
|--------|-------|-------------------|
| Power-i 3-way agree → naked applied | high | `power_i_agree` |
| Power-i buckets when sources agree | high | `power_i_agree` |
| Power-i blocked / sources disagree / name mismatch | low (keep prior value) | same string as `power_attention` |
| Trusted Power-i but large delta vs store | medium on applied power | `power_i_large_delta` |
| Roster OCR only | medium | `roster_ocr` |
| Stars from vision | medium | `stars_vision` |
| Manual edit / API PATCH of that field | high | `manual_confirm` |
| Power auto-rescaled after star/pellet edit | medium | `scaled_from_stars` |
| Legacy unscored | medium | `legacy_unscored` |

Field notes:

- **power:** roster card OCR alone never becomes **high**; Power-i agree or manual confirm does.
- **stars / pellets / level:** typically medium unless manually confirmed.
- **buckets:** only when Power-i captured; disagree → low and do not overwrite safer prior buckets when we keep them.

## UI (heroes inventory)

- Paint **cells**, not whole rows: `data-assurance="low|medium|high"` on level / stars / pellets / power cells.
- CSS: low → red tint; medium → amber; high → no tint.
- Title/tooltip shows the short reason.
- Replace read-only power cell with auto-save number input (`data-field="power"`), same pattern as stars/pellets.
- PATCH already accepts `power`; response includes updated assurance so JS can refresh cell attributes.
- Explicit power edit → assurance **high** / `manual_confirm`.
- Remove incomplete-lock that prevented power from being fixed once power is editable.
- Trust / incomplete: row incomplete if any painted field is **low**, or power/stars missing (same spirit as today’s attention).

## Components

- `ks/heroes/assurance.py` — levels, `FieldAssurance`, mark helpers, ladder apply
- `HeroRecord.assurance` — serialize/deserialize
- Collector write paths set assurance when writing fields
- `update_hero_stars` / PATCH: explicit field → high; auto-scaled power → medium
- One-shot migrate on load (or small helper) for `legacy_unscored`
- Template + CSS + `inventory.js` for cell paint and power edit

## Errors

- Invalid power on PATCH → existing validation (no silent clamp).
- Corrupt assurance map → degrade to medium, keep numeric values.

## Tests

- Ladder: agree → high; attention → low; OCR → medium; manual → high; scale → medium
- Store round-trip of `assurance`
- PATCH power → high; star change without explicit power → scaled medium
- Incomplete when any field is low
- API/template: power editable; payload exposes assurance

## Success criteria

- Every shown hero number has a level + reason in store/API.
- Low cells are red; medium amber; high quiet.
- Naked power can be edited in the heroes inventory and becomes high.
- Same naked power on two heroes does not by itself mark either low.
