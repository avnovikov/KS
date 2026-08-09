# Optimiser governor + skills — umbrella backlog

**Date:** 2026-08-09  
**Status:** Active (docs-only backlog; no new GitHub issues)  
**Idea:** [conquest-combat-and-optimiser-skills.md](conquest-combat-and-optimiser-skills.md)  
**Designs:** [conquest sim-lite](../superpowers/specs/2026-08-09-conquest-combat-sim-lite-design.md) · [all optimisers](../superpowers/specs/2026-08-09-governor-skills-all-optimisers-design.md)  
**Plan:** [2026-08-09-governor-skills-all-optimisers.md](../superpowers/plans/2026-08-09-governor-skills-all-optimisers.md)

External cross-links only (do not create/update issues from this board): GitHub [#41](https://github.com/avnovikov/KS/issues/41)–[#47](https://github.com/avnovikov/KS/issues/47).

## Locked product choices

| Topic | Choice |
|-------|--------|
| Success | Correct model first, then validate rankings vs Conquest/Arena clears |
| Scope | Full optimiser list (Bear → Swordland → Arena/Conquest → Gear XP → Molten) |
| Conquest fidelity | Sim-lite |
| Ladders | Hybrid (seed known ultimates; linear fallback) |
| Backlog home | `docs/ideas/` + `docs/superpowers/` |

## Dependency order

```text
OG-01 (sim-lite + ladders)
  └─► OG-02 (Arena + Conquest scorers)
        └─► OG-05 (Governor → Arena/Conquest)
OG-03 (Governor → Bear) ──┐
OG-04 (Governor → Sword) ─┼─► OG-06 (Governor → Gear XP)
OG-07 (Expedition hardening) may parallel OG-03
OG-08 (Molten stub) after governor helper is stable
OG-09 (validation) after OG-02 (and ideally OG-05)
```

## Story board

| ID | Title | Status | Depends | GH ref |
|----|-------|--------|---------|--------|
| OG-01 | Shared Conquest sim-lite module + hybrid ladders in catalog | Done | — | — |
| OG-02 | Wire leveled Conquest skills into Arena + Conquest scorers | Done | OG-01 | #44/#45 skills half |
| OG-03 | Governor → Bear Trap (damage / host) | Done | governor store (done) | #42 |
| OG-04 | Governor → Swordland | Done | governor store | #43 |
| OG-05 | Governor → Arena / Conquest | Done | OG-02 | #44/#45 |
| OG-06 | Governor → Gear XP event utility | Done | OG-03 or OG-04 (any child U) | #46 |
| OG-07 | Expedition skill hardening (effect_op / joiner gaps) | Done | skill levels (done) | — |
| OG-08 | Molten Fort optimiser (design stub → later build) | Planned (build: mystic-trial plan) | governor helper | #47 |
| OG-09 | Validation checklist vs known clears | Blocked (wait for next clear) | OG-02 | — |

---

## OG-01 — Shared Conquest sim-lite + hybrid ladders

**Goal:** Introduce `ks/heroes/optimize/conquest_combat.py` (name may vary) and catalog ladder schema so skill coeffs are not treated as Attack%.

**Acceptance:**

- [ ] Kinds split: coeff kinds (`damage_up`, `aoe_damage_up`) vs stat kinds (`attack_up`, `defense_up`, …) vs rate/amp (`attack_speed_up`, enemy damage taken) vs heal.
- [ ] `leveled_value(skill, level)` uses `ladder[level-1]` when present, else `max_value * level/5`.
- [ ] At least one seeded ultimate ladder in catalog (e.g. Amadeus Combo Slash Damage Up 160…224).
- [ ] Unit tests cover ladder vs linear fallback and score monotonicity when coeff rises.
- [ ] Spec math matches [conquest-combat-sim-lite-design](../superpowers/specs/2026-08-09-conquest-combat-sim-lite-design.md).

---

## OG-02 — Wire Conquest skills into Arena + Conquest

**Goal:** Formation scoring uses sim-lite SkillDPS × Toughness instead of `_CONQUEST_KIND_LABELS` folding damage coeffs into Hero Attack.

**Acceptance:**

- [ ] `_CONQUEST_KIND_LABELS` no longer maps `damage_up` / `aoe_damage_up` (and preferably `attack_speed_up` / `crit_rate_up`) into Attack flats.
- [ ] `combat_formation` / `optimize_arena` / `optimize_conquest` consume sim-lite hero scores.
- [ ] Manual skill levels affect Conquest family scores (parity with expedition leveling path).
- [ ] Regression tests: Amadeus-style high coeff ranks above equal-power hero with low coeff when Attack flats equal.

---

## OG-03 — Governor → Bear Trap

**Goal:** Host / damage path includes `governor_troop_bonuses()` Atk%/Def% (and set bonuses) for the relevant troop types.

**Acceptance:**

- [ ] Bear damage (or host strength) changes when governor inventory upgrades.
- [ ] Zero/empty governor store behaves as today’s baseline.
- [ ] Unit fixture with fixed troops + governor percents.

---

## OG-04 — Governor → Swordland

**Goal:** Expedition ILP / recommend path multiplies or adds governor troop Atk%/Def% into march strength consistently with Radiant.

**Acceptance:**

- [ ] Swordland mode score moves when governor Atk% for a used troop type changes.
- [ ] Shared helper — no duplicated set-bonus math.
- [ ] Tests on `recommend` / contribution strength.

---

## OG-05 — Governor → Arena / Conquest

**Goal:** After sim-lite, fold governor bonuses into Conquest-facing offense/toughness (troop escort side and/or effective Attack where design specifies).

**Acceptance:**

- [ ] Arena attack/defense and Conquest optimisers read governor store.
- [ ] Documented where governor applies (escort vs hero sheet) in the all-optimisers design.
- [ ] Tests with governor on/off.

---

## OG-06 — Governor → Gear XP

**Goal:** Gear XP outer search `U()` inherits governor via child event utilities (sword/bear/arena) without a separate ad-hoc formula.

**Acceptance:**

- [ ] Enabling governor changes delta-U for at least one event path in fixtures.
- [ ] No double-counting when multiple child modes run.

---

## OG-07 — Expedition skill hardening

**Goal:** Close remaining gaps: wrong `effect_kind`, missing joiner/`effect_op` treatment for Bear, widget-tagged effects, utility skills that should not inflate combat score.

**Acceptance:**

- [x] Catalog kinds for roster combat heroes reviewed; no silent drop of Defense/Health expedition buffs where intended.
- [x] Bear host/joiner path documents which skills count (align with existing SkillMod work).
- [x] Tests for at least one previously broken kind link.

---

## OG-08 — Molten Fort (stub → build)

**Goal:** Governor-primary mystic room optimiser (Radiant-like slice).

**Design / plan:** [mystic-trial Coliseum/Molten/Radiant v1.1](../superpowers/specs/2026-08-09-mystic-trial-coliseum-molten-design.md) · [plan](../superpowers/plans/2026-08-09-mystic-trial-coliseum-molten.md)

**Acceptance (stub phase):**

- [x] Problem, inputs, and “done” criteria written under the all-optimisers design (Molten section).
- [x] No production UI required in stub phase.

**Acceptance (build phase — in progress):**

- [ ] Shared mystic-trial shell + Molten page/API with governor-primary scoring.
- [ ] Seed ratio ~60/15/25; tests show governor Atk% moves score.

---

## OG-09 — Validation checklist

**Goal:** Compare optimiser rankings to real clears after OG-02 (and again after OG-05).

**Log:** [conquest-arena-validation-log.md](conquest-arena-validation-log.md)

**Status:** Blocked — red banner on the log; validate after another Conquest clear / roster update (no independent comparison this session).

**Acceptance:**

- [x] Checklist doc or section listing: stage/Arena result, top-3 optimiser lineups before/after, pass/fail notes.
- [ ] At least one recorded comparison session filled in (manual).
- [ ] Open calibration notes for α / AoE factor filed back into the sim-lite spec if needed.

---

## Status legend

| Status | Meaning |
|--------|---------|
| Stub | Design text only |
| Planned | Ready for a coding worktree |
| In progress | Active branch |
| Done | Merged + acceptance checked |
