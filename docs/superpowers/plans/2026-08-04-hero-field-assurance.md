# Hero Field Assurance Levels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist high/medium/low assurance (+ reason) on every hero progression number; paint low=red / medium=amber in the heroes inventory; make naked power editable with manual_confirm → high.

**Architecture:** New `ks/heroes/assurance.py` owns levels and helpers. `HeroRecord.assurance` stores a field→`FieldAssurance` map (JSON + SQLite JSON column). Collector and `update_hero_stars` set levels via the source ladder. Inventory template/CSS/JS paint cells and expose a power input.

**Tech Stack:** Python 3, existing `HeroStore` / FastAPI inventory UI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-04-hero-field-assurance-design.md`

## Global Constraints

- Levels are only `high` | `medium` | `low` (plus short reason string)
- Fields: `power`, `stars`, `level`, `pellets`, `from_level`, `from_stars`, `from_skills`, `gear_strength`
- Same naked power across heroes must NOT lower assurance
- Roster OCR alone never makes `power` high
- Manual PATCH of a field → that field `high` / `manual_confirm`
- Star/pellet auto-rescale of power → `medium` / `scaled_from_stars`
- Legacy missing assurance → `medium` / `legacy_unscored` (not low)
- Cell paint only (not whole-row red for assurance); trust incomplete if any painted field is low
- Work only in the feature worktree; commit after each task; TDD

## File map

| File | Responsibility |
|------|----------------|
| `ks/heroes/assurance.py` | Types + ladder helpers + migrate |
| `ks/heroes/models.py` | `HeroRecord.assurance` |
| `ks/heroes/store.py` | Persist assurance (JSON + SQLite TEXT) |
| `ks/heroes/ui/app.py` | `update_hero_stars` sets assurance; PATCH echoes it |
| `ks/heroes/collector.py` | Set assurance on OCR / Power-i writes |
| `ks/heroes/ui/trust.py` | Incomplete when any low assurance |
| `ks/heroes/ui/templates/inventory_heroes.html` | Editable power + `data-assurance` |
| `ks/heroes/ui/static/app.css` | low/medium cell tints |
| `ks/heroes/ui/static/inventory.js` | Refresh assurance attrs after PATCH |
| `tests/test_heroes_assurance.py` | Ladder + migrate + incomplete |
| `tests/test_heroes_store_assurance.py` | Round-trip |
| `tests/test_heroes_ui_assurance.py` | PATCH + trust |

---

### Task 1: `assurance.py` core + unit tests

**Files:**
- Create: `ks/heroes/assurance.py`
- Create: `tests/test_heroes_assurance.py`

**Interfaces:**
- Produces:
  - `AssuranceLevel = Literal["high", "medium", "low"]`
  - `@dataclass(frozen=True) class FieldAssurance: level: AssuranceLevel; reason: str`
  - `ASSURANCE_FIELDS: frozenset[str]` — the eight field names
  - `field_assurance(level: str, reason: str) -> FieldAssurance` — normalizes unknown level → medium
  - `set_field(assurance: Mapping, field: str, level: str, reason: str) -> dict[str, FieldAssurance]`
  - `assurance_to_dict(assurance: Mapping[str, FieldAssurance]) -> dict`
  - `assurance_from_dict(data: Any) -> dict[str, FieldAssurance]`
  - `ensure_legacy(assurance, *, present_fields: Mapping[str, Any]) -> dict[str, FieldAssurance]` — for each present numeric/value field in ASSURANCE_FIELDS missing from map, add medium/`legacy_unscored`
  - `has_low(assurance: Mapping[str, FieldAssurance], fields: Iterable[str] | None = None) -> bool`

- [ ] **Step 1: Write failing tests**

```python
from ks.heroes.assurance import (
    FieldAssurance,
    assurance_from_dict,
    assurance_to_dict,
    ensure_legacy,
    field_assurance,
    has_low,
    set_field,
)

def test_field_assurance_unknown_level_becomes_medium():
    a = field_assurance("wat", "x")
    assert a.level == "medium"
    assert a.reason == "x"

def test_set_field_and_round_trip_dict():
    m = set_field({}, "power", "high", "manual_confirm")
    assert m["power"] == FieldAssurance("high", "manual_confirm")
    assert assurance_from_dict(assurance_to_dict(m)) == m

def test_ensure_legacy_fills_missing_only():
    m = set_field({}, "power", "high", "manual_confirm")
    out = ensure_legacy(m, present_fields={"power": 1, "stars": 3})
    assert out["power"].level == "high"
    assert out["stars"] == FieldAssurance("medium", "legacy_unscored")

def test_has_low():
    m = set_field({}, "power", "low", "power_i_sources_disagree")
    assert has_low(m) is True
    assert has_low(set_field({}, "power", "high", "manual_confirm")) is False
```

- [ ] **Step 2: Run tests — expect FAIL (import error)**

Run: `pytest tests/test_heroes_assurance.py -v`

- [ ] **Step 3: Implement `ks/heroes/assurance.py`** (minimal; keep functions small)

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add ks/heroes/assurance.py tests/test_heroes_assurance.py
git commit -m "feat(heroes): add field assurance types and helpers"
```

---

### Task 2: `HeroRecord.assurance` + store round-trip + migrate on load

**Files:**
- Modify: `ks/heroes/models.py`
- Modify: `ks/heroes/store.py`
- Create: `tests/test_heroes_store_assurance.py`

**Interfaces:**
- Consumes: Task 1 helpers
- Produces: `HeroRecord.assurance: dict[str, FieldAssurance]` default `{}`; included in `to_dict`/`from_dict`; store JSON persists it; SQLite column `assurance_json TEXT` (ALTER if missing); `_load_existing_json` runs `ensure_legacy` for present progression fields so every stored value has an entry

Present fields for legacy: power, stars, level, pellets (and any bucket keys if later stored on the record — v1 only the four roster fields unless buckets are already on the record; if buckets are only in power_history, skip them on HeroRecord until Task 4 stores them — **v1: only power/stars/level/pellets on the record**)

Note: Spec lists buckets on the assurance map when captured. If buckets are not fields on `HeroRecord`, store them only under `assurance` keys when collector has them in a follow-up — for Task 2, support arbitrary keys in the map via from_dict, but legacy fill only the four roster fields.

- [ ] **Step 1: Failing test — round-trip**

```python
from pathlib import Path
from ks.heroes.assurance import FieldAssurance
from ks.heroes.models import HeroRecord
from ks.heroes.store import HeroStore

def test_store_round_trips_assurance(tmp_path: Path):
    store = HeroStore(tmp_path)
    hero = HeroRecord(
        name="Gordon",
        power=262120,
        stars=3,
        scraped_at="t",
        assurance={"power": FieldAssurance("high", "manual_confirm")},
    )
    store.upsert(hero)
    store2 = HeroStore(tmp_path)
    got = next(h for h in store2.all_heroes() if h.name == "Gordon")
    assert got.assurance["power"].level == "high"
    assert got.assurance["power"].reason == "manual_confirm"
    # stars present without assurance → legacy filled on load
    assert got.assurance["stars"].reason == "legacy_unscored"

def test_hero_record_dict_round_trip():
    h = HeroRecord(name="A", power=1, scraped_at="t",
                   assurance={"power": FieldAssurance("medium", "roster_ocr")})
    h2 = HeroRecord.from_dict(h.to_dict())
    assert h2.assurance["power"].level == "medium"
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Wire models + store (JSON + `assurance_json` column)**

- [ ] **Step 4: PASS + commit**

```bash
git commit -m "feat(heroes): persist per-field assurance on HeroRecord"
```

---

### Task 3: PATCH / `update_hero_stars` sets assurance

**Files:**
- Modify: `ks/heroes/ui/app.py` (`update_hero_stars`)
- Create or extend: `tests/test_heroes_ui_assurance.py` (or existing heroes UI patch tests if present — search first)

**Interfaces:**
- Consumes: `set_field`, `FieldAssurance`
- Behavior:
  - Explicit PATCH field in `{stars,pellets,level,power}` → that field `high`/`manual_confirm`
  - If stars/pellets change and power was auto-scaled (not explicit) → `power` `medium`/`scaled_from_stars`
  - API JSON for hero includes `assurance` via `to_dict`

- [ ] **Step 1: Failing tests**

```python
def test_patch_power_sets_high_manual(tmp_path, ...):
    # upsert hero with medium power assurance
    # call update_hero_stars(..., power=238487)
    # assert assurance["power"] == FieldAssurance("high", "manual_confirm")

def test_star_change_scales_power_medium(tmp_path, ...):
    # hero power=100000 stars=2
    # update stars=3 without power
    # assert power changed and assurance["power"].reason == "scaled_from_stars"
    # assert assurance["stars"].reason == "manual_confirm"
```

- [ ] **Step 2–4: TDD implement, pass, commit**

```bash
git commit -m "feat(heroes): set assurance on inventory PATCH"
```

---

### Task 4: Collector ladder on write

**Files:**
- Modify: `ks/heroes/collector.py` (where power/stars/level/pellets upserted and where Power-i applies)
- Extend: `tests/test_heroes_collector.py` and/or `tests/test_heroes_assurance.py`

**Interfaces:**
- On roster OCR write of power/level/stars/pellets → `medium`/`roster_ocr` for those written fields (unless Power-i immediately overwrites power)
- On Power-i trusted apply → `power` `high`/`power_i_agree`; if soft large delta → `medium`/`power_i_large_delta`
- On Power-i blocked (`power_attention` set, value not applied) → keep prior power; set `power` assurance `low` with attention reason (use `getattr(hero, "power_attention", None)` / the reason string)
- If Power-i buckets are recorded onto the hero or into assurance keys only: when agree, set bucket keys `high`/`power_i_agree`; when disagree, set those keys `low` with disagreement reason **without** requiring new HeroRecord numeric fields — optional: only set assurance keys for buckets when breakdown is trusted/stored. Minimal: at least set `power` assurance correctly; if breakdown is stored elsewhere, also `set_field` for `from_level`/`from_stars`/`from_skills`/`gear_strength` on the assurance map when values were read.

- [ ] **Step 1: Failing tests** with fake scrape stubs (follow existing collector test patterns)

- [ ] **Step 2–4: Implement, pass, commit**

```bash
git commit -m "feat(heroes): collector sets field assurance from source ladder"
```

---

### Task 5: Trust incomplete when any low

**Files:**
- Modify: `ks/heroes/ui/trust.py`
- Extend: `tests/test_heroes_assurance.py` or trust tests

**Interfaces:**
- `hero_row_incomplete`: True if stars/power None **or** `power_attention` **or** `has_low(hero.assurance, ("power","stars","level","pellets"))`

- [ ] TDD + commit

```bash
git commit -m "feat(heroes): treat low field assurance as incomplete"
```

---

### Task 6: Inventory UI — editable power + cell paint

**Files:**
- Modify: `ks/heroes/ui/templates/inventory_heroes.html`
- Modify: `ks/heroes/ui/static/app.css`
- Modify: `ks/heroes/ui/static/inventory.js`
- Modify: hint text to mention editable power + assurance colors

**Behavior:**
- Replace read-only power cell with number input `data-field="power"` (min/max matching API `_POWER_MIN`/`_POWER_MAX` if exposed; else reasonable 0..9999999), `data-blank="null"`, `data-required` optional — power can be blank for incomplete
- Remove `data-incomplete-locked` when power is editable
- Wrap level/stars/pellets/power cells (or inputs) with `data-assurance="{{ h.assurance[...] }}"` and `title="{{ reason }}"` — use a tiny Jinja macro or inline: level from `h.assurance.get('level')` etc. If missing, omit attribute (or medium legacy after migrate)
- CSS:
  ```css
  .data-table td[data-assurance="low"],
  .data-table td[data-assurance="low"] .cell-input { /* red tint */ }
  .data-table td[data-assurance="medium"],
  .data-table td[data-assurance="medium"] .cell-input { /* amber tint */ }
  ```
- `inventory.js`: after successful PATCH, if payload.hero.assurance present, set `data-assurance` and title on the corresponding cells; update power cell like other inputs (may need to stop treating `.power-cell` as text-only — use input like stars)

- [ ] Manual smoke optional; add a small template/unit test if the repo has HTML tests — otherwise JS change covered by existing inventory patterns + one API test that response includes assurance (already Task 3)

- [ ] Commit

```bash
git commit -m "feat(heroes): paint assurance cells and edit naked power"
```

---

### Task 7: Verify suite

- [ ] Run: `pytest tests/test_heroes_assurance.py tests/test_heroes_store_assurance.py tests/test_heroes_ui_assurance.py tests/test_heroes_collector.py tests/test_heroes_sanitize_power.py -v` (and any new trust tests)
- [ ] Fix failures
- [ ] Commit only if fixes needed
- [ ] Mark plan checkboxes done in this file in a final docs commit if desired

---

## Spec coverage checklist

| Spec item | Task |
|-----------|------|
| Persist assurance map | 1–2 |
| Source ladder (OCR/Power-i/manual/scale/legacy) | 3–4 |
| Cell paint low/medium | 6 |
| Editable naked power → high | 3, 6 |
| Incomplete on low | 5 |
| Same power across heroes OK | 4 (no cross-hero check) |
| Buckets in assurance when captured | 4 (assurance keys) |
| Out of scope gear/optimizer | — |
