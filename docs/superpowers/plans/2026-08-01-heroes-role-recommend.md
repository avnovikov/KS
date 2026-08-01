# Heroes Role Recommend Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an ILP-based recommender that picks role/mode + 3 heroes + troop counts to maximize expected personal Relic Points from scraped roster + manual troops.

**Architecture:** `ks/heroes/optimize/` loads instance roster, joins hybrid catalog, solves one PuLP ILP per mode, returns best mode and alternatives via `ks-heroes recommend`.

**Tech Stack:** Python 3.12, PuLP+CBC, PyYAML, pytest; reuses `HeroRecord` / `HeroStore`.

## Global Constraints

- Workspace: `.worktrees/feature-heroes-collector` on `feature/heroes-collector`
- Objective is expected **personal** points; engine chooses mode unless `--force-role`
- Single march only; no ADB in recommend path
- Dependency: add `pulp` to `pyproject.toml` dependencies

## File map

| File | Responsibility |
|------|----------------|
| `ks/heroes/optimize/__init__.py` | Package exports |
| `ks/heroes/optimize/types.py` | TroopsConfig, CatalogEntry, Scenario, RecommendResult |
| `ks/heroes/optimize/catalog.py` | Load KingshotPro JSON + hero_catalog.yaml; join by name |
| `ks/heroes/optimize/scenarios.py` | Load point_scenarios.yaml |
| `ks/heroes/optimize/scoring.py` | Per-hero strength score for a mode |
| `ks/heroes/optimize/model.py` | Build/solve ILP for one mode |
| `ks/heroes/optimize/recommend.py` | Evaluate modes; pick max |
| `ks/heroes/cli.py` | Add `recommend` subcommand |
| `config/troops.yaml` | Example troop inventory |
| `config/hero_catalog.yaml` | Widget + effect tags (seed core heroes) |
| `config/point_scenarios.yaml` | Mode priors |
| `tests/test_heroes_optimize_*.py` | Unit tests |

---

### Task 1: Types + troops config loader

**Files:**
- Create: `ks/heroes/optimize/__init__.py`
- Create: `ks/heroes/optimize/types.py`
- Create: `ks/heroes/optimize/troops.py`
- Create: `config/troops.yaml`
- Test: `tests/test_heroes_optimize_troops.py`

**Interfaces:**
- Produces: `TroopsConfig(infantry: int, cavalry: int, archers: int, march_capacity: int)`, `load_troops_config(path) -> TroopsConfig`

- [ ] **Step 1: Write failing test**

```python
from pathlib import Path
from ks.heroes.optimize.troops import load_troops_config

def test_load_troops_config(tmp_path: Path):
    p = tmp_path / "troops.yaml"
    p.write_text("infantry: 100\ncavalry: 20\narchers: 30\nmarch_capacity: 150\n")
    cfg = load_troops_config(p)
    assert cfg.infantry == 100
    assert cfg.cavalry == 20
    assert cfg.archers == 30
    assert cfg.march_capacity == 150
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_heroes_optimize_troops.py -v`  
Expected: FAIL import error

- [ ] **Step 3: Minimal implementation**

Implement frozen `TroopsConfig` and YAML loader; reject negative counts.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_heroes_optimize_troops.py -v`  
Expected: PASS

- [ ] **Step 5: Commit** (only if user requested commits)

---

### Task 2: Catalog join (KingshotPro + YAML)

**Files:**
- Create: `ks/heroes/optimize/catalog.py`
- Create: `config/hero_catalog.yaml` (seed: Amadeus, Zoe, Howard, Petra, Saul, Chenko, Quinn)
- Test: `tests/test_heroes_optimize_catalog.py`

**Interfaces:**
- Produces: `CatalogEntry(name, gen, troop, rarity, widget_type, rally_tier, garrison_tier, joiner_tier, effects: list[EffectTag])`
- `load_catalog(pro_path, yaml_path) -> dict[str, CatalogEntry]`
- `EffectTag(kind: str, max_value: float, applies_to: str)` — kinds: `attack_up`, `damage_taken_down`, `rally_attack`, `defender_attack`, `lethality_up`, …

- [ ] **Step 1: Failing test** — join Amadeus from fixture pro JSON + YAML widget `attack`

- [ ] **Step 2: Verify fail**

- [ ] **Step 3: Implement loaders + join (case-insensitive name)**

- [ ] **Step 4: Pass**

---

### Task 3: Scenarios + scoring

**Files:**
- Create: `ks/heroes/optimize/scenarios.py`
- Create: `ks/heroes/optimize/scoring.py`
- Create: `config/point_scenarios.yaml`
- Test: `tests/test_heroes_optimize_scoring.py`

**Interfaces:**
- `Scenario(mode, combat_rate, minutes_held, personal_rate, p_first, first_bonus, loot_expected, enemy_power_scale, formation_weights: dict)`
- `hero_strength(hero: HeroRecord, entry: CatalogEntry, mode: str) -> float`
- Joiner mode: weight first expedition effect only; solo: ignore widget tags

- [ ] **Step 1: Failing test** — Zoe defense widget scores higher than Amadeus under `garrison` scoring; reverse under `rally_lead`

- [ ] **Step 2–4:** Implement and pass

---

### Task 4: ILP model (one mode)

**Files:**
- Modify: `pyproject.toml` — add `pulp>=2.8`
- Create: `ks/heroes/optimize/model.py`
- Test: `tests/test_heroes_optimize_model.py`

**Interfaces:**
- `solve_mode(heroes, catalog, troops, scenario) -> ModeSolution(heroes, troops, expected_points, breakdown, capacity)`

Constraints as in spec. Objective linearizes:
`points ≈ combat_rate/10000 * enemy_power_scale * (sum x_h*strength_h + wI*tI + wC*tC + wA*tA) + occupation + first + loot`

Use big-M / indicator only if needed; prefer prefiltering infeasible heroes for mode widget rules then require count of widget heroes ≥ 1 via sum.

- [ ] **Step 1: Failing test** — 6-hero fake roster, capacity 100, owned 60/20/20 → selects 3, respects ownership, capacity includes escorts

- [ ] **Step 2–4:** Add pulp, implement, pass

---

### Task 5: Recommend across modes + CLI

**Files:**
- Create: `ks/heroes/optimize/recommend.py`
- Modify: `ks/heroes/cli.py`
- Test: `tests/test_heroes_optimize_recommend.py`
- Test: `tests/test_heroes_cli_recommend.py`

**Interfaces:**
- `recommend(heroes, catalog, troops, scenarios, force_mode=None) -> RecommendResult`
- CLI writes JSON to `--out` (default `artifacts/heroes/recommend_result.json`)

- [ ] **Step 1: Failing test** — defense-heavy fixture → `garrison`; attack-heavy → `rally_lead`

- [ ] **Step 2–4:** Implement recommend loop + CLI; pass

---

### Task 6: Seed configs + smoke

**Files:**
- Ensure example YAMLs documented in spec paths
- Optional: script or CLI note to curl KingshotPro cache

- [ ] **Step 1: Add `config/point_scenarios.yaml` with realistic Swordland priors**
- [ ] **Step 2: Run full optimize test suite**
- [ ] **Step 3: Manual dry run with fixture heroes.json**

---

## Self-review

- Spec coverage: ILP, role choice, personal points, hybrid catalog, troops, capacity, CLI — all tasked
- No placeholders in task interfaces
- Types consistent: `TroopsConfig`, `CatalogEntry`, `Scenario`, `ModeSolution`, `RecommendResult`
