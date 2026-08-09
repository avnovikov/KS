# Mystic Trial Coliseum / Molten / Radiant v1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shared mystic-trial optimiser shell, Radiant floor stubs + MC (#37/#38), then Coliseum and Molten Fort full page/API slices.

**Architecture:** Extract ratio + proxy from `radiant_spire.py` into `ks/heroes/optimize/mystic_trial/`; room adapters supply seed ratios and % stacks; floors/MC plug into Radiant first; Coliseum/Molten reuse shell with different focus.

**Tech Stack:** Python 3, FastAPI/Jinja UI (existing heroes UI), YAML config, pytest.

**Spec:** [docs/superpowers/specs/2026-08-09-mystic-trial-coliseum-molten-design.md](../specs/2026-08-09-mystic-trial-coliseum-molten-design.md)

## Global Constraints

- No new GitHub issues; link #37/#38/#47 only.
- Proxy banner whenever engine is proxy: `Proxy score — not in-game clear prediction.`
- Governor Atk%/Def% maps already include set bonuses — never double-add.
- Conquest sim-lite coeffs must not feed mystic-trial expedition % stacks.
- Work only under `.worktrees/`; one concern per PR phase when practical.
- TDD: failing test before production code for each task.

---

### Task 1: Shared ratio + proxy module (Radiant behavior-preserving)

**Files:**
- Create: `ks/heroes/optimize/mystic_trial/__init__.py`
- Create: `ks/heroes/optimize/mystic_trial/ratios.py` (move `ratio_candidates`, `counts_for_ratio`, `_normalize_ratio`)
- Create: `ks/heroes/optimize/mystic_trial/proxy.py` (move `score_march`, `MarchScore`)
- Modify: `ks/heroes/optimize/radiant_spire.py` — import from mystic_trial; keep public API
- Test: `tests/test_mystic_trial_ratios.py` (new) + existing `tests/test_radiant_spire.py`

**Interfaces:**
- Produces: `normalize_ratio`, `ratio_candidates(*, step=0.05)`, `counts_for_ratio(ratio, capacity, owned)`, `score_march(...)` → `MarchScore`

- [ ] **Step 1: Write failing test** that imports `ks.heroes.optimize.mystic_trial.ratios.ratio_candidates` and asserts seed 50/15/35 present

- [ ] **Step 2: Run test — expect FAIL (module missing)**

```bash
pytest tests/test_mystic_trial_ratios.py -v
```

- [ ] **Step 3: Implement ratios.py + proxy.py; re-export from radiant_spire**

- [ ] **Step 4: Run `pytest tests/test_mystic_trial_ratios.py tests/test_radiant_spire.py -q` — PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
refactor(heroes): extract mystic-trial ratio and proxy helpers

EOF
)"
```

---

### Task 2: Room config YAML + loader

**Files:**
- Create: `config/mystic_trial/radiant_spire.yaml` (seed 50/15/35, focus `all`, marches 2)
- Create: `config/mystic_trial/coliseum.yaml` (seed 50/10/40, focus `heroes_gear`, marches 1)
- Create: `config/mystic_trial/molten_fort.yaml` (seed 60/15/25, focus `governor`, marches 1)
- Create: `ks/heroes/optimize/mystic_trial/rooms.py` (`RoomConfig`, `load_room`)
- Test: `tests/test_mystic_trial_rooms.py`

**Interfaces:**
- Produces: `RoomConfig(id, seed_ratio, published_ratios, focus, active_marches, schema_marches)`

- [ ] **Step 1: Failing test — load molten_fort seed is 60/15/25 and focus is governor**

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Minimal YAML + loader**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(mystic-trial): room YAML configs and loader

EOF
)"
```

---

### Task 3: Radiant floor stubs (#37)

**Files:**
- Create: `config/mystic_trial/radiant_spire_floors.yaml`
- Create: `ks/heroes/optimize/mystic_trial/floors.py`
- Test: `tests/test_mystic_trial_floors.py`
- Modify: radiant API/page to accept optional floor id (still proxy score)

**Interfaces:**
- Produces: `load_floors(path) -> dict[int, FloorStub]`, `FloorStub(floor, enemy_ratio, enemy_power_scale)`

- [ ] **Step 1: Failing test — floor 10 enemy ratio ≈ 53/27/20**

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Seed YAML + loader; wire `?floor=` on radiant API returning stub metadata**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(radiant): enemy floor stub database (#37)

EOF
)"
```

---

### Task 4: Radiant MC / multi-round engine (#38)

**Files:**
- Create: `ks/heroes/optimize/mystic_trial/combat_mc.py`
- Modify: `radiant_spire.py` / room runner to choose MC when floor present
- Test: `tests/test_mystic_trial_combat_mc.py`
- Modify: UI floor selector + show `engine: mc|proxy`

**Interfaces:**
- Consumes: `FloorStub`, march counts, unit stats, atk/def % maps
- Produces: `simulate_floor(...) -> McResult(win_rate, remaining_hp_est, rounds)`

- [ ] **Step 1: Failing test — with stub, MC win_rate in [0,1]; without floor, optimize stays proxy**

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Minimal deterministic multi-round (not full Monte Carlo variance) + optional sample count later**

- [ ] **Step 4: PASS + radiant tests still green**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(radiant): floor combat engine with proxy fallback (#38)

EOF
)"
```

---

### Task 5: Coliseum optimiser + UI

**Files:**
- Create: `ks/heroes/optimize/mystic_trial/coliseum.py` (`optimize_coliseum`)
- Modify: `ks/heroes/ui/optimize_run.py`, `app.py`, `_subnav_optimiser.html`
- Create: `templates/optimiser_coliseum.html`, `static/optimiser_coliseum.js` (clone radiant single-march)
- Test: `tests/test_coliseum_optimize.py`

**Interfaces:**
- Consumes: heroes, catalog, gear, troops; **governor weight 0 by default**
- Produces: same JSON shape as radiant with `active_marches=1`

- [ ] **Step 1: Failing test — higher hero Attack% raises coliseum score; governor Atk% alone does not (default)**

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Adapter + page + `/api/optimize/coliseum`**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(coliseum): mystic-trial ratio optimiser page and API

EOF
)"
```

---

### Task 6: Molten Fort optimiser + UI (OG-08)

**Files:**
- Create: `ks/heroes/optimize/mystic_trial/molten.py` (`optimize_molten`)
- Modify: UI subnav, templates, `optimize_run.py`, `app.py`
- Test: `tests/test_molten_fort_optimize.py`
- Modify: `docs/ideas/optimiser-governor-skills-backlog.md` — OG-08 Done

**Interfaces:**
- Consumes: governor bonuses required; heroes optional/light
- Produces: radiant-compatible JSON; seed 60/15/25

- [ ] **Step 1: Failing test — doubling governor archer Atk% raises molten score**

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Adapter + page + `/api/optimize/molten-fort`**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit + mark OG-08 Done in backlog**

```bash
git commit -m "$(cat <<'EOF'
feat(molten): governor-primary mystic-trial optimiser (OG-08)

EOF
)"
```

---

### Task 7: Docs cross-links + umbrella note

**Files:**
- Modify: radiant design Part C → point at mystic-trial design
- Modify: governor-skills-all-optimisers Molten section → Done / link plan
- Optional: `docs/ideas/mystic-trial-rooms.md` one-pager

- [ ] **Step 1: Update cross-links**

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: link mystic-trial Coliseum/Molten/Radiant v1.1 design

EOF
)"
```

---

## Self-review vs spec

| Spec requirement | Task |
|------------------|------|
| Shared kernel | 1–2 |
| Radiant #37 floors | 3 |
| Radiant #38 MC | 4 |
| Coliseum full slice | 5 |
| Molten full slice / OG-08 | 6 |
| No new GH issues | Global |
| Proxy fallback | 4 |
