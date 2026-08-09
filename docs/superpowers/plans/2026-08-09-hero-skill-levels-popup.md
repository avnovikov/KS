# Hero skill levels popup — Implementation Plan

> **For agentic workers:** Steps use checkbox syntax. TDD. Commit after each task.

**Goal:** Catalog-backed skill list in hero detail popup (2 columns), levels 1–5 overwrite OCR, optimisers use `(level/5)×max_value`.

**Architecture:** Extend `hero_catalog.yaml` + `CatalogEntry`; scrape/seed skills from kingshotmastery; PATCH skills on `HeroStore`; score via `skill_effects`; edit UI in `hero_detail.js` (2-col grid).

**Tech Stack:** Python, FastAPI UI, YAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-09-hero-skill-levels-popup-design.md`

**Worktree:** `.worktrees/feature-hero-skill-levels-popup`

---

### Task 1: Catalog skills model + load

**Files:** `ks/heroes/optimize/types.py`, `ks/heroes/optimize/catalog.py`, `tests/test_hero_catalog_skills.py`

- [ ] RED: load Chenko-style skills from fixture/yaml
- [ ] GREEN: `CatalogSkill` + parse on `CatalogEntry`
- [ ] Commit

### Task 2: Seed skills from kingshotmastery (roster)

**Files:** `scripts/seed_hero_catalog_skills.py` (or `ks/heroes/catalog_skills_fetch.py`), update `config/hero_catalog.yaml`

- [ ] Fetch HTML for roster hero pages; parse Conquest/Expedition skill names
- [ ] Map known expedition skills to `effect_kind` where `effects` already exist
- [ ] Write skills into catalog; cite source in file header
- [ ] Commit

### Task 3: Scoring uses skill levels

**Files:** `ks/heroes/optimize/skill_effects.py`, tests

- [ ] RED: level 5 → full max_value; level 1 → 0.2×
- [ ] GREEN: `leveled_catalog_percents(hero, entry)` wired into `family_percents`
- [ ] Commit

### Task 4: API overwrite skills

**Files:** `ks/heroes/ui/app.py`, `ks/heroes/store.py` if needed, tests

- [ ] RED/GREEN: `PATCH /api/heroes/{name}/skills` replaces skills with slot/name/level 1–5
- [ ] Commit

### Task 5: Hero detail popup UI (2 columns)

**Files:** `ks/heroes/ui/static/hero_detail.js`, CSS in page or `app.css`, API GET may include catalog skills

- [ ] Fetch catalog skills + current levels
- [ ] Render 2-column grid; +/- saves via PATCH
- [ ] Smoke test
- [ ] Commit

### Task 6: Verify

- [ ] pytest subset green; restart UI and manually set a skill level; Radiant rank moves
