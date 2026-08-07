# Bear Trap SkillMod v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or executing-plans. Steps use checkbox syntax.

**Goal:** Op-bucketed SkillMod for Bear `rally_lead` from host catalog skills + assumed joiners.

**Architecture:** Pure functions in `bear_damage.py`; `BeartrapBuffs` carries research + joiner list; `model.py` fills host buckets at extract time.

**Tech Stack:** Python, pytest, existing catalog `EffectTag.effect_op`.

## Global Constraints

- TDD: failing tests before production code.
- Do not double-apply gear expedition % into SkillMod.
- Keep `skillmod=1` guide fixture tests unchanged when no buffs.

---

### Task 1: SkillMod product math

**Files:** `ks/heroes/optimize/bear_damage.py`, `tests/test_bear_damage.py`

- [ ] Test: same-op 4×25 → 2.0; mixed 2×101+2×102 at 25 → 2.25
- [ ] Test: full skillmod with research × damage / defense
- [ ] Implement `bucket_sum_product`, `compute_skillmod`

### Task 2: Host buckets from catalog + joiner YAML

**Files:** `bear_damage.py`, `config/beartrap_buffs.yaml`, tests

- [ ] Test: Chenko-style lethality_up op 101 enters DamageUp
- [ ] Test: load assumed joiners 2+2 from YAML
- [ ] Implement `damage_up_buckets_from_effects`, extend `BeartrapBuffs` / loader

### Task 3: Wire model extract

**Files:** `ks/heroes/optimize/model.py`, `tests/test_heroes_optimize_beartrap.py`

- [ ] Test: recommend rally_lead score rises when host has lethality_up op 101 vs none
- [ ] Pass host+joiner skillmod into `greedy_fill_march`
- [ ] Breakdown includes bucket maps

### Task 4: Verify

- [ ] `pytest tests/test_bear_damage.py tests/test_heroes_optimize_beartrap.py -q`
