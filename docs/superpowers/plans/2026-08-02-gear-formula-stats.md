# Formula-first gear stats — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Score gear from rarity+level+mastery formulas so Gear XP spend sees positive ΔU.

**Architecture:** New `ks/heroes/optimize/gear_stats.py` loads tier params from `pieces_and_stats.yaml` (with code defaults). `piece_score` and rarity caps consume it; OCR unused for scoring.

**Tech Stack:** Python, existing pytest, YAML config.

## Global Constraints

- Formula-first; OCR sanity only
- No invented Grey/Green base/max
- Epic slope uses cap 80 (0.0021/level), not /100

---

### Task 1: `expedition_stat_fraction` + tests

**Files:**
- Create: `ks/heroes/optimize/gear_stats.py`
- Create: `tests/test_heroes_gear_stats.py`
- Modify: `config/hero_gear_optimizer/pieces_and_stats.yaml`

- [ ] Write failing tests (mythic/epic/blue/red/mastery/unknown)
- [ ] Implement loader + formula
- [ ] Update YAML with Blue tier + formula notes

### Task 2: `piece_score` + caps

**Files:**
- Modify: `ks/heroes/optimize/gear_assign.py`
- Modify: `ks/heroes/optimize/xp_ladder.py`
- Modify: `tests/test_heroes_xp_ladder.py`
- Create/modify: tests for piece_score level sensitivity

- [ ] Failing test: score rises when enhancement rises (OCR stats frozen)
- [ ] Wire `piece_score` to formula
- [ ] Fix `cap_for_rarity` for blue/green/grey

### Task 3: Verify Gear XP end-to-end

- [ ] Run spend against live inventory (or fixture); expect steps or ΔU > 0 when bag non-empty
- [ ] Restart UI if needed
