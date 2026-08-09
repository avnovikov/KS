# Governor + skills all optimisers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement docs-backed stories OG-01…OG-09: Conquest sim-lite + hybrid ladders, wire Arena/Conquest, then governor (and expedition hardening) across Bear, Swordland, Arena/Conquest, Gear XP; Molten remains stub until a later plan.

**Architecture:** Shared `governor_troop_bonuses()` for expedition/Conquest escort layers; new `conquest_combat` scoring for Arena/Conquest; expedition paths keep SkillMod / ILP. Catalog gains optional `ladder` lists with linear fallback.

**Tech Stack:** Python 3, pytest, existing `ks/heroes/optimize/*`, hero catalog YAML/JSON, governor store.

## Global Constraints

- Work only in a git worktree under `.worktrees/` (never primary checkout).
- One coding concern per worktree/branch (e.g. `feature/conquest-combat-sim-lite` separate from `feature/governor-bear`).
- Do not create GitHub issues; update [docs/ideas/optimiser-governor-skills-backlog.md](../../ideas/optimiser-governor-skills-backlog.md) status when a story completes.
- Conquest coeffs never feed Expedition SkillMod; Expedition percents never feed sim-lite coeffs.
- Manual skill levels 1–5 remain scoring SoT; ignore noisy OCR `current_bonus` when levels exist (existing behavior).
- ADB-first for device actions if any capture is added later; this plan is optimiser math only.

---

### Task 1: OG-01 — Conquest sim-lite module + hybrid ladders

**Files:**
- Create: `ks/heroes/optimize/conquest_combat.py`
- Modify: `ks/heroes/optimize/skill_effects.py` (leveled value helper with ladder)
- Modify: catalog models / seed data under `ks/heroes/optimize/catalog.py` (or existing catalog skill schema) + seed script or YAML for Amadeus/Vivian/Petra ultimates
- Test: `tests/test_conquest_combat.py`

**Interfaces:**
- Consumes: `HeroRecord`, catalog entry/skills, stored skill levels, conquest flat Attack/Defense/Health
- Produces: `ConquestCombatBreakdown(atk_eff, skill_dps, toughness, score, incomplete)` and `conquest_hero_score(...)`; `leveled_effect_value(max_value, level, ladder=None) -> float`

- [ ] **Step 1: Write failing tests for ladder resolution and score shape**

```python
def test_leveled_effect_value_uses_ladder():
    assert leveled_effect_value(224.0, 1, [160, 176, 192, 208, 224]) == 160.0
    assert leveled_effect_value(224.0, 5, [160, 176, 192, 208, 224]) == 224.0

def test_leveled_effect_value_linear_fallback():
    assert leveled_effect_value(100.0, 5, None) == 100.0
    assert leveled_effect_value(100.0, 1, None) == 20.0

def test_conquest_hero_score_scales_with_coeff_ladder():
    # fixture hero with fixed Hero Attack, one damage_up skill level 1 vs 5
    low = conquest_hero_score(hero_lv1, entry, catalog=cat)
    high = conquest_hero_score(hero_lv5, entry, catalog=cat)
    assert high.skill_dps > low.skill_dps
    assert high.score > low.score
```

- [ ] **Step 2: Run tests — expect FAIL (import/missing symbols)**

Run: `pytest tests/test_conquest_combat.py -v`  
Expected: FAIL collecting or `leveled_effect_value` / `conquest_hero_score` not defined

- [ ] **Step 3: Implement `leveled_effect_value` + `conquest_hero_score` per sim-lite design**

Implement formulas from [2026-08-09-conquest-combat-sim-lite-design.md](../specs/2026-08-09-conquest-combat-sim-lite-design.md): Atk_eff, SkillDPS sum, Toughness, Score = SkillDPS × Toughness^α with α=0.5 defaults.

- [ ] **Step 4: Seed three ultimate ladders in catalog data**

Amadeus Combo Slash `damage_up` 160…224; Vivian Gilded Barrage `aoe_damage_up` 180…252; Petra Dichotomy `damage_up` 270…378. Comment source: Kingshot Mastery Conquest guide.

- [ ] **Step 5: Run tests — expect PASS**

Run: `pytest tests/test_conquest_combat.py -v`  
Expected: PASS

- [ ] **Step 6: Commit on feature branch**

```bash
git add ks/heroes/optimize/conquest_combat.py ks/heroes/optimize/skill_effects.py tests/test_conquest_combat.py
# plus catalog seed files touched
git commit -m "$(cat <<'EOF'
feat: add Conquest sim-lite scoring and hybrid skill ladders

EOF
)"
```

Mark OG-01 Done on the backlog board.

---

### Task 2: OG-02 — Wire sim-lite into Arena + Conquest

**Files:**
- Modify: `ks/heroes/optimize/combat_formation.py`
- Modify: `ks/heroes/optimize/arena.py`
- Modify: `ks/heroes/optimize/conquest.py`
- Modify: `ks/heroes/optimize/stat_contributions.py` (stop mapping coeff kinds to Attack flats for optimiser objective)
- Test: `tests/test_heroes_stat_contributions.py`, `tests/test_conquest_combat.py` (formation integration), existing arena/conquest tests if present

**Interfaces:**
- Consumes: `conquest_hero_score` from Task 1
- Produces: formation `base_score` driven by sim-lite; contribution explain may still show flats for non-coeff kinds

- [ ] **Step 1: Write failing test — high coeff ultimate beats equal-power low coeff**

```python
def test_formation_prefers_higher_damage_up_ladder():
    # two heroes identical Attack flats; only skill ladder level differs
    assert score_with(hero_high_ultimate) > score_with(hero_low_ultimate)
```

- [ ] **Step 2: Run test — expect FAIL under old Attack-flat folding**

- [ ] **Step 3: Wire `combat_formation` base score to `conquest_hero_score`; remove `damage_up`/`aoe_damage_up`/`attack_speed_up`/`crit_rate_up`/`heal_up` from `_CONQUEST_KIND_LABELS` Attack/Health folding used by the objective**

- [ ] **Step 4: Run arena/conquest + new tests — expect PASS**

Run: `pytest tests/test_conquest_combat.py tests/test_heroes_stat_contributions.py -v`  
(plus any `tests/test_*arena*` / `tests/test_*conquest*`)

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat: score Arena and Conquest with sim-lite skill DPS

EOF
)"
```

Mark OG-02 Done.

---

### Task 3: OG-03 — Governor → Bear Trap

**Files:**
- Modify: `ks/heroes/optimize/bear_damage.py` (and callers in recommend/bundle if needed)
- Test: `tests/test_bear_damage_governor.py` (or extend existing bear tests)

**Interfaces:**
- Consumes: `governor_troop_bonuses()` from `ks/heroes/governor_bonuses.py`
- Produces: Bear damage/host strength including governor Atk%/Def%

- [ ] **Step 1: Failing test — governor Atk% increases bear damage vs empty store**

```python
def test_bear_damage_rises_with_governor_attack_pct():
    base = bear_damage(..., governor=empty)
    buffed = bear_damage(..., governor=with_archer_atk)
    assert buffed > base
```

- [ ] **Step 2: Implement wiring; empty governor ≡ current baseline**

- [ ] **Step 3: pytest PASS; commit**

```bash
git commit -m "$(cat <<'EOF'
feat: include governor troop bonuses in Bear Trap damage

EOF
)"
```

Mark OG-03 Done.

---

### Task 4: OG-04 — Governor → Swordland

**Files:**
- Modify: `ks/heroes/optimize/model.py` and/or `stat_contributions.py` expedition path / `recommend.py`
- Test: `tests/test_swordland_governor.py` (or existing recommend tests)

**Interfaces:**
- Consumes: `governor_troop_bonuses()`
- Produces: Swordland mode scores sensitive to governor troop Atk%/Def%

- [ ] **Step 1: Failing test — sword recommend score changes when cavalry Atk% rises**

- [ ] **Step 2: Apply same composition rule as Radiant (document in `governor_bonuses` docstring)**

- [ ] **Step 3: pytest PASS; commit**

```bash
git commit -m "$(cat <<'EOF'
feat: include governor troop bonuses in Swordland scoring

EOF
)"
```

Mark OG-04 Done.

---

### Task 5: OG-05 — Governor → Arena / Conquest

**Files:**
- Modify: `ks/heroes/optimize/conquest_combat.py` (escort weight) and/or `combat_formation.py`
- Test: `tests/test_conquest_combat.py`

**Interfaces:**
- Consumes: Task 1 score + `governor_troop_bonuses()`
- Produces: scores that change with governor when escort weight > 0

- [ ] **Step 1: Failing test — governor Def% increases toughness/score**

- [ ] **Step 2: Implement escort mixing per all-optimisers design (default `escort_dps_weight=0.15`)**

- [ ] **Step 3: pytest PASS; commit; mark OG-05 Done**

---

### Task 6: OG-06 — Governor → Gear XP

**Files:**
- Modify: `ks/heroes/optimize/spend_xp.py` only if child U() does not already see governor after Tasks 3–5; otherwise add integration test only
- Test: `tests/test_gear_xp_governor.py`

- [ ] **Step 1: Integration test — delta-U changes when governor store upgrades for sword or bear child**

- [ ] **Step 2: Fix double-counting if any; PASS; commit; mark OG-06 Done**

```bash
git commit -m "$(cat <<'EOF'
test: assert Gear XP utility inherits governor via child events

EOF
)"
```

---

### Task 7: OG-07 — Expedition skill hardening

**Files:**
- Modify: `ks/heroes/optimize/skill_effects.py`, catalog seed/links, possibly `bear_damage.py`
- Test: `tests/test_skill_effects_hardening.py`

- [ ] **Step 1: List roster heroes with missing/wrong `effect_kind`; write one failing test per fixed class (Defense drop, widget-tagged max, joiner op)**

- [ ] **Step 2: Fix catalog/kind_family; PASS; commit; mark OG-07 Done**

---

### Task 8: OG-08 — Molten Fort stub only

**Files:**
- Modify: this plan’s sibling design already contains Molten section — ensure backlog OG-08 stays Stub
- Optional: `docs/ideas/molten-fort.md` one-pager if a later session needs a dedicated idea file

- [ ] **Step 1: Confirm Molten build criteria remain design-only; no optimiser module in this wave**

- [ ] **Step 2: Mark OG-08 Stub (not Done) on backlog until a dedicated Molten implementation plan exists**

---

### Task 9: OG-09 — Validation checklist

**Files:**
- Create: `docs/ideas/conquest-arena-validation-log.md`

- [ ] **Step 1: Add template table**

```markdown
| Date | Mode | Known result | Top-3 before | Top-3 after | Pass? | Notes |
|------|------|--------------|--------------|-------------|-------|-------|
```

- [ ] **Step 2: After OG-02 (and again after OG-05), fill at least one real comparison row**

- [ ] **Step 3: If α / aoe_targets need changes, amend sim-lite spec defaults in the same PR as the calibration note**

- [ ] **Step 4: Mark OG-09 Done when one comparison is recorded**

---

## Self-review (plan vs specs)

| Spec requirement | Task |
|------------------|------|
| Sim-lite formulas + hybrid ladders | Task 1 |
| Stop folding damage coeffs into Attack flats; wire Arena/Conquest | Task 2 |
| Governor Bear / Sword / Arena-Conquest / Gear XP | Tasks 3–6 |
| Expedition hardening | Task 7 |
| Molten stub | Task 8 |
| Validate rankings vs clears | Task 9 |
| No new GitHub issues | Global Constraints |
| Expedition SkillMod separate from Conquest coeffs | Global Constraints + Tasks 1–2 |

No TBD placeholders in task steps. Types/names: `ConquestCombatBreakdown`, `conquest_hero_score`, `leveled_effect_value`, `governor_troop_bonuses` are consistent across Tasks 1–6.

## Execution handoff

When starting code: open a **new** worktree per wave (OG-01/02 first), use subagent-driven-development or executing-plans, and update the umbrella backlog statuses as stories complete.
