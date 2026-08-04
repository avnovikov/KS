# Stat Contributions Across Event Lineups & Optimisers — Implementation Plan (v2, rebased on origin/main)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split every hero's power and combat stats into hero / skills / gear shares for the event-correct family (conquest vs expedition), make every optimiser score from those shares, and surface them on the Event lineups board and hero sheet.

**Architecture:** Two leaf modules already own all estimation — `skill_effects.py` turns scraped skill text into family-tagged percent bonuses, `stat_contributions.py` composes hero + skills + gear into a `StatContribution` and exposes per-family strength scalars. Both are merged (Tasks 1-2). This plan wires them through every scorer: the `effective_power` + `gear_bonus` keyword pair is retired in favour of a `StatContribution`, the API payload carries `stat_family` / `formation_totals` / per-hero `contributions`, and `optimiser_events.js` renders them inside the existing Apple-light design system.

**Tech Stack:** Python 3.11+, dataclasses, `pulp` (CBC) ILP, PyYAML, pytest, FastAPI + Jinja2, vanilla ES5-style JS in `ks/heroes/ui/static/`.

## v2 — why this plan was rewritten

v1 was derived against a branch **89 commits behind `origin/main`**. Main had since rewritten `model.py` (+445 lines), `explain.py` (+239), `recommend.py` (+222), `spend_xp.py` (+166), `optimize_run.py` (+156), `gear_assign.py` (+101), `combat_formation.py` (+58), and **deleted** `ks/heroes/ui/templates/optimize_events.html` — v1 Task 8's entire target — replacing it with `templates/optimiser_events.html` + `static/optimiser_events.js` and a 726-line JS test suite. Tasks 1-2 were unaffected (new files only) and rebased cleanly. Every task below is re-derived against main's actual code. (v1 is recoverable at commit `5bc8f6b`.)

## Global Constraints

- Base worktree: `/Users/alexei/KS/.worktrees/feature-stat-contributions-optimizers`, branch `feature/stat-contributions-optimizers`, rebased on `origin/main`.
- Run tests with `uv run pytest` from the worktree root — the ambient `python3` lacks `discord`/`h3` and fails collection on 5 unrelated files.
- **Known pre-existing failure**, present on unmodified `origin/main`, not to be fixed here: `tests/test_heroes_optimize_gear_assign.py::test_best_sets_picks_highest_score_per_slot`.
- No new runtime dependencies.
- `estimated` is always `True` on every `StatContribution` (rule A is an estimate; scraping the in-game popup is out of scope).
- Conquest stat labels are exactly: `Hero Attack`, `Hero Defense`, `Hero Health`, `Escort Attack`, `Escort Defense`, `Escort Health`.
- Expedition stat labels are `<TroopPrefix> <Stat>`, TroopPrefix ∈ {`Infantry`, `Cavalry`, `Archer`} (**singular `Archer`** — what gear OCR emits), Stat ∈ {`Attack`, `Defense`, `Health`, `Lethality`}.
- Conquest shares are flat values that sum; expedition shares are percent points that sum additively.
- Invariant for every `Share`: `hero >= 0`, `skills >= 0`, `gear >= 0`, `total == hero + skills + gear`.
- Tests assert wiring and invariants, never frozen pre-change score values. **ILP scores will change — that is the point.**
- **Circular-import rule (measured):** `scoring.py` and `gear_assign.py` MUST NOT import `stat_contributions` at module level. Two 2-hop cycles exist: `scoring → stat_contributions → gear_assign → scoring`, and `scoring → stat_contributions → skill_effects → scoring`. Use a function-local import (the codebase already does this at `recommend.py:101`, `explain.py:213`, `explain.py:411`). Module-level imports are safe in `model.py`, `explain.py`, `recommend.py`, `combat_formation.py`, `front_survival.py`, `opponent_models.py`, `survival_pipeline.py`, `spend_xp.py`, `optimize_run.py`.
- **The six PR #26 invariants pinned by `tests/test_heroes_pr26_bugbot.py` must survive.** Listed under "PR #26 invariants" below; every task that touches them says so.

## Measured calibration note (state it, don't hide it)

Replacing `40.0 * power/1e6 + gear_bonus + rarity_bonus` with `40.0 * contribution_strength(...)`, measured on the live roster with a 4-piece infantry set assigned:

| Hero | old power term | old gear | old rarity | old sum | new `40×cs` |
|------|---------------|----------|-----------|---------|-------------|
| Jabel | 17.11 | 9.28 | 8.0 | **34.39** | **59.08** |
| Diana | 14.12 | 9.28 | 4.0 | **27.39** | **52.10** |
| Howard | 11.82 | 9.28 | 4.0 | **25.10** | **50.43** |
| Forrest | 8.71 | 9.28 | 0.0 | **17.99** | **44.95** |
| Helga | 7.15 | 9.28 | 8.0 | **24.43** | **41.18** |

The strength term roughly **doubles** and its spread **compresses** (1.9× → 1.4×). Against `arena_value * star` (~40-95), strength moves from ~25-40% of the base score to ~40-55%: lineups become more stat-driven and less role-driven. This follows directly from locked Decision 3 ("rewrite every scorer around contributions") and is why the plan forbids asserting old score values. Do not silently re-tune the `40.0` coefficient to hide it; restoring the old balance would be a separate, explicit decision.

## PR #26 invariants (must survive every task)

From `tests/test_heroes_pr26_bugbot.py`:

1. `test_gear_bonus_uses_assigned_pieces_not_repooled` — a per-hero gear signal derived from an **already-assigned** gear map must never flatten pieces back into a pool and re-assign by roster power.
2. `test_heuristic_offense_honors_conquest_base_score` — foe heuristic offense for Conquest must apply `ultimate_level_multiplier`.
3. `test_sanitize_hero_powers_catalog_usable_median` — the sanitize median must be computed over the same catalog-usable cohort the ILP uses.
4. `test_slot_utilities_include_gear_bonus` — `slot_utilities`' `U_front`/`U_back` must include the gear signal. **v1 of this plan would have broken this by passing `gear_bonus=0.0`; v2 passes gear-bearing contributions instead.**
5. `test_provisional_gear_priority_uses_sanitized_power` — provisional gear-claim priority must rank by sanitized, not raw OCR, power.
6. `test_opponent_from_formation_keeps_explicit_assignment_bonus` — `opponent_from_formation` must honour an explicit `gear_assignment` rather than deriving its own.

Also pinned, by `tests/test_heroes_survival_api.py`: `GET /api/optimize` must return, for `arena.attack`, `arena.defense` and `conquest`, a `survival` block with `score_eff` and `foes`, plus `sensitivity` with a non-empty `win_summary` and exactly the variant ids `{baseline, gear_f2_first, gear_back_first, swap_front, swap_front_f1_gear}`, with `baseline.delta_score_eff == 0.0`.

## Execution Waves

| Wave | Tasks | Worktree(s) |
|------|-------|-------------|
| 1 (parallel) | 3 expedition, 4 conquest | `sc-expedition`, `sc-conquest` |
| 2 (parallel, after wave 1 merged) | 5 survival + sanitize, 6 spend_xp | `sc-survival`, `sc-spendxp` |
| 3 (parallel, after wave 2 merged) | 7 API, 8 UI | `sc-api`, `sc-ui` |
| 4 | 9 regression suite | base worktree |

Wave 3 parallelises safely because Task 7's **Interfaces** block freezes the JSON contract Task 8 renders.

---

## Task 3: Expedition scoring path

**Worktree:** `sc-expedition` — parallel with Task 4.

**Files:**
- Modify: `ks/heroes/optimize/scoring.py:110-131` (`hero_strength`)
- Modify: `ks/heroes/optimize/model.py:125-151` (`_compute_hero_features`), `:363` (`solve_mode` keyword), `:371` (call site)
- Modify: `ks/heroes/optimize/explain.py:210` / `:281` (keyword), `:226` (forward), `:300-313` (`hero_strength` call)
- Modify: `ks/heroes/optimize/recommend.py:62` / `:98` (keyword), `:74` / `:113` (forward), `:141-157` (`_build_gear_assignment`), `:177` (gear map), `:209-220` (result)
- Modify: `ks/heroes/optimize/types.py:138-169` (`RecommendResult`)
- Modify: `ks/heroes/optimize/gear_assign.py:160-167` (delete)
- Test: `tests/test_heroes_optimize_scoring.py`, `tests/test_heroes_optimize_recommend.py`

**Interfaces:**
- Consumes: `EXPEDITION`, `hero_contribution`, `formation_contribution`, `contribution_strength`, `family_for_event`, `StatContribution`.
- Produces:
  - `hero_strength(hero, entry, mode, *, event=None, contribution=None) -> float` — `effective_power` and `gear_bonus` **removed**.
  - `solve_mode(..., gear_by_troop: dict[str, dict[str, GearRecord]] | None = None, ...)` replaces `gear_bonus_by_troop`.
  - `leave_one_out_mode(..., gear_by_troop=...)`, `explain_selected_heroes(..., gear_by_troop=...)` likewise.
  - `RecommendResult` gains `stat_family: str = "expedition"` and `formation_totals: dict[str, Any] | None = None`, both emitted by `to_dict()`; each row in `.heroes` gains `"contributions"`.
  - `gear_assign.gear_bonus_by_troop` **deleted**.

- [ ] **Step 1: Write the failing scoring tests**

Append to `tests/test_heroes_optimize_scoring.py` (it already defines `_entry`):

```python
import pytest

from ks.heroes.optimize.stat_contributions import EXPEDITION, Share, StatContribution


def _contribution(power: float, lethality: float = 0.0) -> StatContribution:
    return StatContribution(
        family=EXPEDITION,
        estimated=True,
        skills_incomplete=False,
        power=Share(hero=power, skills=0.0, gear=0.0),
        stats={"Infantry Lethality": Share(0.0, 0.0, lethality)},
    )


def test_hero_strength_rises_with_contribution_power() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    low = hero_strength(hero, entry, "solo", contribution=_contribution(100_000))
    high = hero_strength(hero, entry, "solo", contribution=_contribution(900_000))
    assert high > low


def test_hero_strength_rises_with_contribution_gear_percent() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    bare = hero_strength(hero, entry, "solo", contribution=_contribution(100_000))
    geared = hero_strength(
        hero, entry, "solo", contribution=_contribution(100_000, lethality=40.0)
    )
    assert geared > bare


def test_hero_strength_without_contribution_scores_effects_only() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3, power=100_000)
    assert hero_strength(hero, entry, "solo") == hero_strength(
        hero, entry, "solo", contribution=None
    )


def test_hero_strength_rejects_conquest_contribution() -> None:
    entry = _entry("Zoe", "defense")
    hero = HeroRecord(name="Zoe", stars=3)
    wrong = StatContribution(
        family="conquest",
        estimated=True,
        skills_incomplete=False,
        power=Share(1.0, 0.0, 0.0),
        stats={},
    )
    with pytest.raises(ValueError, match="expedition"):
        hero_strength(hero, entry, "solo", contribution=wrong)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_heroes_optimize_scoring.py -v`
Expected: FAIL — `TypeError: hero_strength() got an unexpected keyword argument 'contribution'`

- [ ] **Step 3: Rewrite `hero_strength`**

Replace `ks/heroes/optimize/scoring.py:110-131` with:

```python
def hero_strength(
    hero: HeroRecord,
    entry: CatalogEntry,
    mode: str,
    *,
    event: EventProfile | None = None,
    contribution: "StatContribution | None" = None,
) -> float:
    """Mode-weighted effect score plus the hero's expedition contribution.

    ``contribution`` must be an expedition-family ``StatContribution``; it
    replaces the old ``effective_power`` + ``gear_bonus`` pair, so power and
    gear percents enter through one estimated split rather than a raw scrape
    plus a 0.15-scaled heuristic.
    """
    # Local import: scoring is an ancestor of stat_contributions (via both
    # gear_assign and skill_effects), so a module-level import is circular.
    from ks.heroes.optimize.stat_contributions import (
        EXPEDITION,
        contribution_strength,
    )

    weights, op_weights = _resolve_mode_weights(mode, event)
    total = sum(
        _effect_tag_value(tag, hero, mode, weights, op_weights)
        for tag in entry.effects
    )
    total += _widget_priority_bonus(entry, mode)

    if contribution is not None:
        if contribution.family != EXPEDITION:
            raise ValueError(
                "hero_strength needs an expedition contribution; got "
                f"{contribution.family!r}"
            )
        total += contribution_strength(contribution)
    return total
```

Add to the top of `scoring.py`, after the existing imports:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — runtime import is function-local
    from ks.heroes.optimize.stat_contributions import StatContribution
```

- [ ] **Step 4: Rewrite `_compute_hero_features`**

Replace the `strengths` construction in `ks/heroes/optimize/model.py:125-151`. Keep the rest of the function body (the `_warn_missing_escorts` / `escorts` / `widget` / `_HeroFeatures(...)` tail) exactly as it stands; change only the parameter name and the `strengths` dict:

```python
def _compute_hero_features(
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    scenario: Scenario,
    event: EventProfile | None,
    gear_by_troop: dict[str, dict[str, GearRecord]] | None,
) -> _HeroFeatures:
    troop_of = {
        h.name: (normalize_troop(catalog[h.name].troop) or "") for h in usable
    }
    # Gear is fungible within a troop class: score power using the best geared
    # hero of that class (widgets / skills / stars stay on the selected hero).
    class_power = max_power_by_troop(usable, catalog)
    gear = gear_by_troop or {}
    strengths = {
        h.name: hero_strength(
            h,
            catalog[h.name],
            scenario.mode,
            event=event,
            contribution=hero_contribution(
                h,
                catalog[h.name],
                family=EXPEDITION,
                gear_pieces=gear.get(troop_of[h.name]),
                power=class_power.get(troop_of[h.name], h.power),
                catalog=catalog,
            ),
        )
        for h in usable
    }
```

Add to `model.py`'s module-level imports (safe — no cycle):

```python
from ks.heroes.gear_models import GearRecord
from ks.heroes.optimize.stat_contributions import EXPEDITION, hero_contribution
```

Rename the `solve_mode` keyword at `model.py:363` to:

```python
    gear_by_troop: dict[str, dict[str, GearRecord]] | None = None,
```

and update the `_compute_hero_features(...)` call at `model.py:371` to pass it.

- [ ] **Step 5: Update `explain.py`**

Rename the keyword on `leave_one_out_mode` (`explain.py:210`) and `explain_selected_heroes` (`explain.py:281`) to:

```python
    gear_by_troop: dict[str, dict[str, GearRecord]] | None = None,
```

Forward as `gear_by_troop=gear_by_troop` at the `solve_mode` call (`explain.py:226`) and at the `leave_one_out_mode` call inside `explain_selected_heroes`.

Replace the `hero_strength` call at `explain.py:300-313` with:

```python
        strength = None
        if entry is not None and hero is not None:
            strength = hero_strength(
                hero,
                entry,
                scenario.mode,
                event=event,
                contribution=hero_contribution(
                    hero,
                    entry,
                    family=EXPEDITION,
                    gear_pieces=(gear_by_troop or {}).get(
                        normalize_troop(entry.troop) or ""
                    ),
                    catalog=catalog,
                ),
            )
```

Add to `explain.py`'s module-level imports:

```python
from ks.heroes.gear_models import GearRecord
from ks.heroes.optimize.stat_contributions import EXPEDITION, hero_contribution
```

- [ ] **Step 6: Run the scorer tests, then commit**

Run: `uv run pytest tests/test_heroes_optimize_scoring.py tests/test_heroes_optimize_model.py tests/test_heroes_optimize_explain.py tests/test_heroes_optimize_beartrap.py -v`
Expected: PASS

```bash
git add ks/heroes/optimize/scoring.py ks/heroes/optimize/model.py ks/heroes/optimize/explain.py tests/test_heroes_optimize_scoring.py
git commit -m "feat(heroes): score expedition modes from stat contributions"
```

- [ ] **Step 7: Write the failing recommend tests**

Append to `tests/test_heroes_optimize_recommend.py` (it already defines `_hero` and `_cat`):

```python
import pytest

from ks.heroes.gear_models import GearRecord, GearStats


def _piece(pid: str, troop: str, slot: str, lethality: float) -> GearRecord:
    prefix = "Archer" if troop == "archers" else troop.title()
    return GearRecord(
        piece_id=pid,
        name=f"{troop} {slot}",
        troop_type=troop,
        slot=slot,
        rarity="mythic",
        enhancement_level=40,
        power=50_000,
        stats=GearStats(
            conquest={"Hero Attack": 300},
            expedition={f"{prefix} Lethality": lethality},
            lethality=lethality,
        ),
    )


def _run_recommend():
    heroes = [_hero("Zoe"), _hero("Saul"), _hero("Howard"), _hero("Amadeus")]
    catalog = {
        "Zoe": _cat("Zoe", "infantry", "defense", "defender_attack", 30),
        "Saul": _cat("Saul", "archer", "defense", "defense_up", 20),
        "Howard": _cat("Howard", "cavalry", "none", "damage_taken_down", 20),
        "Amadeus": _cat("Amadeus", "infantry", "attack", "rally_attack", 30),
    }
    troops = TroopsConfig(infantry=80, cavalry=40, archers=40, march_capacity=150)
    scenarios = {
        "garrison": Scenario(
            mode="garrison",
            combat_rate=40,
            minutes_held=50,
            personal_rate=600,
            require_widget="defense",
            enemy_power_scale=50000,
            formation_weights={"infantry": 1.0, "cavalry": 1.0, "archers": 1.0},
        ),
    }
    gear = [
        _piece("i1", "infantry", "helmet", 30.0),
        _piece("c1", "cavalry", "helmet", 25.0),
        _piece("a1", "archers", "helmet", 28.0),
    ]
    return recommend(
        heroes, catalog, troops, scenarios, force_mode="garrison", gear=gear
    )


def test_recommend_result_carries_expedition_contributions() -> None:
    payload = _run_recommend().to_dict()
    assert payload["stat_family"] == "expedition"
    assert set(payload["formation_totals"]["power"]) == {
        "hero", "skills", "gear", "total"
    }
    for row in payload["heroes"]:
        contrib = row["contributions"]
        assert contrib["family"] == "expedition"
        assert contrib["estimated"] is True
        for share in contrib["stats"].values():
            assert share["hero"] >= 0
            assert share["skills"] >= 0
            assert share["gear"] >= 0
            assert share["total"] == pytest.approx(
                share["hero"] + share["skills"] + share["gear"]
            )


def test_recommend_formation_totals_sum_hero_contributions() -> None:
    payload = _run_recommend().to_dict()
    totals = payload["formation_totals"]
    rows = [r["contributions"] for r in payload["heroes"] if r.get("contributions")]
    assert totals["power"]["gear"] == pytest.approx(
        sum(c["power"]["gear"] for c in rows)
    )
    for label, share in totals["stats"].items():
        assert share["total"] == pytest.approx(
            sum((c["stats"].get(label) or {}).get("total", 0.0) for c in rows)
        )
```

- [ ] **Step 8: Run to verify they fail**

Run: `uv run pytest tests/test_heroes_optimize_recommend.py -v`
Expected: FAIL — `KeyError: 'stat_family'`

- [ ] **Step 9: Rewire `recommend.py`**

Replace the gear-bonus computation at `recommend.py:177` with a gear **map**:

```python
    gear_by_troop = best_sets_by_troop(gear, profile=gear_profile) if gear else None
```

Change the `gear_assign` import at the top of `recommend.py` to include `best_sets_by_troop` and drop `gear_bonus_by_troop`. Rename the `gear_bonus` parameter of `_solve_all_modes` (`:62`) and `_explain_hero_rows` (`:98`) to `gear_by_troop`, and forward it as `gear_by_troop=gear_by_troop` at the `solve_mode` call (`:74`) and the `explain_selected_heroes` call (`:113`).

`_build_gear_assignment` (`:141-157`) currently returns only the serialisable form; the raw map is needed for the contributions. Change it to return both:

```python
def _build_gear_assignment(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    best: ModeSolution,
    gear_profile: str,
) -> tuple[
    dict[str, list[dict[str, Any]]] | None,
    dict[str, dict[str, GearRecord]],
]:
    """Return (serialisable assignment, raw slot→piece map per hero)."""
    if not gear:
        return None, {}
    assigned = assign_best_sets(
        heroes,
        catalog,
        gear,
        selected=list(best.hero_names),
        profile=gear_profile,
    )
    return assignment_to_dict(assigned), assigned
```

In `recommend`, unpack both and build the final contributions from the **assigned** gear:

```python
    gear_assignment, assigned = _build_gear_assignment(
        heroes, catalog, gear, best, gear_profile
    )
    stat_family = family_for_event(event.name if event else "swordland")
    hero_by_name = {h.name: h for h in heroes}
    contributions: dict[str, StatContribution] = {}
    for name in best.hero_names:
        hero = hero_by_name.get(name)
        if hero is None:
            continue
        contributions[name] = hero_contribution(
            hero,
            catalog.get(name),
            family=stat_family,
            gear_pieces=assigned.get(name),
            catalog=catalog,
        )
    hero_rows = tuple(
        {
            **row,
            "contributions": (
                contributions[row["name"]].to_dict()
                if row.get("name") in contributions
                else None
            ),
        }
        for row in hero_rows
    )
    formation_totals = (
        formation_contribution(list(contributions.values())).to_dict()
        if contributions
        else None
    )
```

and pass `stat_family=stat_family, formation_totals=formation_totals` on the `RecommendResult(...)` construction at `:209-220`.

Add to `recommend.py`'s module-level imports:

```python
from ks.heroes.optimize.stat_contributions import (
    StatContribution,
    family_for_event,
    formation_contribution,
    hero_contribution,
)
```

- [ ] **Step 10: Extend `RecommendResult`**

In `ks/heroes/optimize/types.py`, add after `gear_assignment` (line 149):

```python
    stat_family: str = "expedition"
    formation_totals: dict[str, Any] | None = None
```

and add to the `out` literal in `to_dict()` (line 152):

```python
            "stat_family": self.stat_family,
            "formation_totals": self.formation_totals,
```

- [ ] **Step 11: Delete the dead gear-bonus heuristic**

`gear_assign.gear_bonus_by_troop` was the `0.15 * set_score` nudge that success criterion 4 retires. Nothing imports it after Step 9. Delete `ks/heroes/optimize/gear_assign.py:160-167` in full. Keep `set_score` and `best_sets_by_troop` — `recommend` now calls the latter.

Run: `grep -rn "gear_bonus_by_troop" ks tests`
Expected: no output.

- [ ] **Step 12: Run the tests**

Run: `uv run pytest tests/test_heroes_optimize_recommend.py tests/test_heroes_recommend_all_modes.py tests/test_heroes_optimize_events.py tests/test_heroes_cli_recommend.py -v`
Expected: PASS

- [ ] **Step 13: Full suite**

Run: `uv run pytest -q`
Expected: PASS except (a) the known pre-existing `test_best_sets_picks_highest_score_per_slot`, and (b) suites owned by Tasks 4-8 that still use the conquest-side `gear_bonus=` keyword. Record the exact failing list in your report; do not fix them here.

- [ ] **Step 14: Commit**

```bash
git add ks/heroes/optimize/recommend.py ks/heroes/optimize/types.py ks/heroes/optimize/gear_assign.py tests/test_heroes_optimize_recommend.py
git commit -m "feat(heroes): attach stat contributions to recommend results"
```

---

## Task 4: Conquest scoring path

**Worktree:** `sc-conquest` — parallel with Task 3.

**Files:**
- Modify: `ks/heroes/optimize/combat_formation.py:35-66` (`CombatFormationResult`), `:100-138` (`hero_base_score`), `:175-188` (`gear_bonus_from_assignment`), `:191-224` (`_provisional_gear_bonus`), `:263-...` (`solve_combat_formation`)
- Modify: `ks/heroes/optimize/arena.py:26-67` (`ArenaResult`), `:86-94` (`_base`)
- Modify: `ks/heroes/optimize/conquest.py:40-57` (`_conquest_base_score`)
- Test: `tests/test_heroes_optimize_combat_formation.py`, `tests/test_heroes_optimize_arena_defense.py`, `tests/test_heroes_optimize_conquest.py`

**Interfaces (load-bearing — Tasks 5-7 are written against these and cannot change them):**
- `hero_base_score(hero, entry, roles, *, effective_power, contribution, side) -> float`
- `base_score_fn` protocol: `fn(hero, entry, roles, *, effective_power, contribution) -> float`
- `contributions_from_assignment(gear_asg, *, catalog, heroes_by_name, power_by_name=None, family=CONQUEST) -> dict[str, StatContribution]` replaces `gear_bonus_from_assignment`
- `_provisional_contributions(usable, catalog, gear, gear_profile, *, family=CONQUEST, power_by_name=None) -> dict[str, StatContribution]` replaces `_provisional_gear_bonus`
- `CombatFormationResult` and `ArenaResult` each gain `stat_family: str = "conquest"`, `contributions: dict[str, dict[str, Any]] | None = None`, `formation_totals: dict[str, Any] | None = None`, all emitted by `to_dict()`

**PR #26 invariants touched:** #1 (assignment-derived signal must not re-pool), #2 (`ultimate_level_multiplier` retained), #5 (provisional claim priority ranks by sanitized power).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_heroes_optimize_combat_formation.py` (currently only 8 lines — add the imports it needs):

```python
import pytest

from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.combat_formation import hero_base_score, solve_combat_formation
from ks.heroes.optimize.stat_contributions import CONQUEST, Share, StatContribution
from ks.heroes.optimize.types import CatalogEntry


def _conq(power: float, attack: float = 0.0, health: float = 0.0) -> StatContribution:
    return StatContribution(
        family=CONQUEST,
        estimated=True,
        skills_incomplete=False,
        power=Share(hero=power, skills=0.0, gear=0.0),
        stats={
            "Hero Attack": Share(attack, 0.0, 0.0),
            "Hero Health": Share(health, 0.0, 0.0),
        },
    )


def _roles() -> dict:
    return {"heroes": {}, "placement": {}, "slots": {"carry_slot": "B2"}}


def test_hero_base_score_rises_with_contribution_power() -> None:
    hero = HeroRecord(name="A", stars=3, power=100_000)
    entry = CatalogEntry(name="A", arena_value=50.0)
    low = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000), side="attack",
    )
    high = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(900_000), side="attack",
    )
    assert high > low


def test_hero_base_score_rises_with_conquest_stats() -> None:
    hero = HeroRecord(name="A", stars=3, power=100_000)
    entry = CatalogEntry(name="A", arena_value=50.0)
    bare = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000), side="attack",
    )
    statted = hero_base_score(
        hero, entry, _roles(), effective_power=100_000,
        contribution=_conq(100_000, attack=5000.0, health=40_000.0), side="attack",
    )
    assert statted > bare


def test_hero_base_score_rejects_expedition_contribution() -> None:
    hero = HeroRecord(name="A", stars=3)
    entry = CatalogEntry(name="A")
    wrong = StatContribution("expedition", True, False, Share(1.0, 0.0, 0.0), {})
    with pytest.raises(ValueError, match="conquest"):
        hero_base_score(
            hero, entry, _roles(), effective_power=None,
            contribution=wrong, side="attack",
        )


def _roster() -> tuple[list[HeroRecord], dict[str, CatalogEntry]]:
    names = ["A", "B", "C", "D", "E"]
    heroes = [
        HeroRecord(
            name=n,
            power=100_000 + 10_000 * i,
            troop_type="infantry" if i < 2 else "archer",
            stars=3,
            stats=HeroStats(
                conquest={
                    "Hero Attack": 1000 + i,
                    "Hero Defense": 900 + i,
                    "Hero Health": 9000 + i,
                }
            ),
        )
        for i, n in enumerate(names)
    ]
    catalog = {
        n: CatalogEntry(
            name=n, troop="infantry" if i < 2 else "archers", arena_value=50.0
        )
        for i, n in enumerate(names)
    }
    return heroes, catalog


def test_solve_combat_formation_emits_contributions() -> None:
    heroes, catalog = _roster()
    result = solve_combat_formation(
        "conquest", heroes, catalog, _roles(),
        gear_slot_order=("F1", "F2", "B2", "B1", "B3"),
        with_explanations=False,
    )
    assert result.status == "Optimal"
    assert result.stat_family == "conquest"
    assert set(result.contributions) == set(result.heroes)
    assert result.formation_totals["power"]["total"] == pytest.approx(
        sum(c["power"]["total"] for c in result.contributions.values())
    )
    payload = result.to_dict()
    assert payload["stat_family"] == "conquest"
    assert payload["formation_totals"] == result.formation_totals
```

Append to `tests/test_heroes_optimize_conquest.py` (reuses its `_catalog()` / `_heroes()`):

```python
def test_conquest_result_dict_carries_contributions() -> None:
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=_catalog())
    payload = optimize_conquest(_heroes(), _catalog(), roles).to_dict()
    assert payload["stat_family"] == "conquest"
    assert set(payload["contributions"]) == set(payload["heroes"])
    for contrib in payload["contributions"].values():
        assert contrib["family"] == "conquest"
        for share in contrib["stats"].values():
            assert share["hero"] >= 0
            assert share["total"] == pytest.approx(
                share["hero"] + share["skills"] + share["gear"]
            )
```

Append the analogous test to `tests/test_heroes_optimize_arena_defense.py`, using that file's own `_roster()` helper and `optimize_arena("attack", ...).to_dict()`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_conquest.py tests/test_heroes_optimize_arena_defense.py -v`
Expected: FAIL — `TypeError: hero_base_score() got an unexpected keyword argument 'contribution'`

- [ ] **Step 3: Rewrite `hero_base_score`**

Replace `ks/heroes/optimize/combat_formation.py:100-138` with:

```python
def hero_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    contribution: StatContribution | None,
    side: str,
) -> float:
    """Compute a hero's base ILP score before placement multipliers.

    Strength comes from ``contribution`` — power plus the hero's conquest stat
    totals, gear included — replacing the old ``power/1e6`` term and the
    0.15-scaled ``gear_bonus`` float. ``effective_power`` remains only as the
    fallback for callers with no contribution to hand.
    """
    meta = _meta_for(hero.name, roles)
    if entry is not None and entry.arena_value is not None:
        arena_value = float(entry.arena_value)
    else:
        arena_value = float(meta.get("arena_value") or 40.0)
    star = star_progress_factor(hero.stars, hero.pellets)
    if contribution is not None:
        if contribution.family != CONQUEST:
            raise ValueError(
                "hero_base_score needs a conquest contribution; got "
                f"{contribution.family!r}"
            )
        strength_term = 40.0 * contribution_strength(contribution)
    else:
        power = effective_power if effective_power is not None else hero.power
        strength_term = 40.0 * (float(power) / 1_000_000.0) if power else 0.0
    rarity_bonus = 0.0
    rarity = (entry.rarity if entry else hero.rarity) or ""
    rarity = rarity.lower()
    if rarity in {"legendary", "mythic"}:
        rarity_bonus = 8.0
    elif rarity == "epic":
        rarity_bonus = 4.0
    base = arena_value * star + strength_term + rarity_bonus

    if side == "defense":
        place = roles.get("defense_placement") or roles.get("placement") or {}
        tags = _hero_tags(hero.name, roles)
        if "tank" in tags:
            base *= float(place.get("tank_tag_bonus", 1.15))
        if "heal" in tags:
            base *= float(place.get("heal_tag_bonus", 1.25))
        if "team_def" in tags:
            base *= float(place.get("team_def_tag_bonus", 1.1))
        if "dps" in tags and "tank" not in tags and "heal" not in tags:
            base *= float(place.get("glass_dps_penalty", 0.92))
    return base
```

Add to `combat_formation.py`'s module-level imports:

```python
from ks.heroes.optimize.stat_contributions import (
    CONQUEST,
    StatContribution,
    contribution_strength,
    family_for_event,
    formation_contribution,
    hero_contribution,
)
```

- [ ] **Step 4: Replace `gear_bonus_from_assignment`**

Replace `ks/heroes/optimize/combat_formation.py:175-188` with:

```python
def contributions_from_assignment(
    gear_asg: dict[str, dict[str, GearRecord]],
    *,
    catalog: dict[str, CatalogEntry],
    heroes_by_name: dict[str, HeroRecord],
    power_by_name: dict[str, int | None] | None = None,
    family: str = CONQUEST,
) -> dict[str, StatContribution]:
    """Contributions from an *already assigned* gear map.

    Must not flatten pieces back into a pool and re-assign by roster power —
    that clobbers explicit exclusive assignments (PR #26 invariant 1). The
    passed map is authoritative: each hero is scored with exactly the pieces
    it holds.
    """
    powers = power_by_name or {}
    out: dict[str, StatContribution] = {}
    for name, slots in gear_asg.items():
        hero = heroes_by_name.get(name)
        if hero is None:
            continue
        out[name] = hero_contribution(
            hero,
            catalog.get(name),
            family=family,
            gear_pieces=slots,
            power=powers.get(name, hero.power),
            catalog=catalog,
        )
    return out
```

- [ ] **Step 5: Replace `_provisional_gear_bonus`**

Replace `ks/heroes/optimize/combat_formation.py:191-224` with:

```python
def _provisional_contributions(
    usable: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear: list[GearRecord] | None,
    gear_profile: str,
    *,
    family: str = CONQUEST,
    power_by_name: dict[str, int | None] | None = None,
) -> dict[str, StatContribution]:
    """Contributions under a provisional exclusive gear assignment.

    The ILP needs a strength signal before it knows the formation, so gear is
    provisionally claimed best-first by *sanitized* power (PR #26 invariant 5).
    The final assignment — and the final contributions — are recomputed once
    the formation is solved.
    """
    powers = power_by_name or {}
    heroes_by_name = {h.name: h for h in usable}

    def _claim_power(row: HeroRecord) -> int:
        value = powers.get(row.name)
        if value is not None:
            return int(value)
        return int(row.power or 0)

    bare = {
        h.name: hero_contribution(
            h,
            catalog.get(h.name),
            family=family,
            gear_pieces=None,
            power=powers.get(h.name, h.power),
            catalog=catalog,
        )
        for h in usable
    }
    if not gear:
        return bare

    score_priority = [
        h.name for h in sorted(usable, key=lambda row: -_claim_power(row))
    ]
    provisional = assign_exclusive_sets(
        usable,
        catalog,
        gear,
        selected=[h.name for h in usable],
        priority=score_priority,
        profile=gear_profile,
    )
    return {
        **bare,
        **contributions_from_assignment(
            provisional,
            catalog=catalog,
            heroes_by_name=heroes_by_name,
            power_by_name=powers,
            family=family,
        ),
    }
```

- [ ] **Step 6: Extend `CombatFormationResult`**

Add three fields after `explanations` (`:47`):

```python
    stat_family: str = CONQUEST
    contributions: dict[str, dict[str, Any]] | None = None
    formation_totals: dict[str, Any] | None = None
```

and to the `out` literal in `to_dict()` (`:50-58`):

```python
            "stat_family": self.stat_family,
            "contributions": self.contributions,
            "formation_totals": self.formation_totals,
```

`_infeasible_result` needs no change — the defaults are right for an infeasible solve.

- [ ] **Step 7: Rewire `solve_combat_formation`**

Replace the provisional-bonus call (`:301-307`) with:

```python
    family = family_for_event(mode)
    contributions = _provisional_contributions(
        usable,
        catalog,
        gear,
        gear_profile,
        family=family,
        power_by_name=power_by_name,
    )
```

Keep the existing `power_by_name = sanitize_hero_powers(...)` line **before** it — sanitized power feeds the provisional claim order (invariant 5).

Replace the `_base_score_fn` default (`:309-316`) and the `base[...]` loop (`:325-331`):

```python
    _base_score_fn = base_score_fn or (
        lambda h, entry, roles, *, effective_power, contribution: hero_base_score(
            h, entry, roles,
            effective_power=effective_power,
            contribution=contribution,
            side=effective_side,
        )
    )
    ...
        base[h.name] = _base_score_fn(
            h,
            catalog.get(h.name),
            roles,
            effective_power=power_by_name.get(h.name, h.power),
            contribution=contributions.get(h.name),
        )
```

Update the docstring line at `:283` to:

```python
    ``base_score_fn`` is called as ``fn(hero, entry, roles, *, effective_power, contribution)``.
```

After the final gear assignment is built (`:372-383`), recompute from the **final** map and roll up:

```python
    final_contributions = contributions_from_assignment(
        {name: (assigned or {}).get(name, {}) for name in ordered},
        catalog=catalog,
        heroes_by_name={h.name: h for h in usable},
        power_by_name=power_by_name,
        family=family,
    )
    formation_totals = formation_contribution(
        list(final_contributions.values())
    ).to_dict()
    contributions_payload = {
        name: c.to_dict() for name, c in final_contributions.items()
    }
```

`assigned` is currently defined only inside `if gear:` — initialise `assigned: dict[str, dict[str, GearRecord]] = {}` before that block. Pass the three fields on the final `CombatFormationResult(...)`:

```python
        stat_family=family,
        contributions=contributions_payload,
        formation_totals=formation_totals,
```

- [ ] **Step 8: Update `arena.py`**

Add the three fields to `ArenaResult` (after `explanations`, `:35`):

```python
    stat_family: str = "conquest"
    contributions: dict[str, dict[str, Any]] | None = None
    formation_totals: dict[str, Any] | None = None
```

carry them in `from_combat` (`:37-49`):

```python
            stat_family=result.stat_family,
            contributions=result.contributions,
            formation_totals=result.formation_totals,
```

add to `to_dict`'s `out` literal (`:53-61`):

```python
            "stat_family": self.stat_family,
            "contributions": self.contributions,
            "formation_totals": self.formation_totals,
```

and update `_base` (`:86-94`):

```python
    def _base(hero, entry, roles, *, effective_power, contribution):
        return hero_base_score(
            hero,
            entry,
            roles,
            effective_power=effective_power,
            contribution=contribution,
            side=side,
        )
```

- [ ] **Step 9: Update `conquest.py`**

Replace `_conquest_base_score` (`:40-57`) — the `ultimate_level_multiplier` factor must stay (invariant 2):

```python
def _conquest_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    contribution: StatContribution | None = None,
) -> float:
    """Base ILP score for Conquest: attack scoring amplified by ultimate level."""
    base = hero_base_score(
        hero,
        entry,
        roles,
        effective_power=effective_power,
        contribution=contribution,
        side="attack",
    )
    return base * ultimate_level_multiplier(hero)
```

Add: `from ks.heroes.optimize.stat_contributions import StatContribution`

- [ ] **Step 10: Run the tests**

Run: `uv run pytest tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_arena_defense.py tests/test_heroes_optimize_conquest.py -v`
Expected: PASS

- [ ] **Step 11: Full suite**

Run: `uv run pytest -q`
Expected: PASS except (a) the known pre-existing gear_assign failure, (b) `tests/test_heroes_pr26_bugbot.py` (imports the renamed helpers), (c) survival / spend_xp / UI suites owned by Tasks 5-8. Record the exact list. **Do not fix `test_heroes_pr26_bugbot.py` here** — Task 5 owns it, because the same tests also exercise `opponent_models` and `survival_pipeline`.

- [ ] **Step 12: Commit**

```bash
git add ks/heroes/optimize/combat_formation.py ks/heroes/optimize/arena.py ks/heroes/optimize/conquest.py tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_conquest.py tests/test_heroes_optimize_arena_defense.py
git commit -m "feat(heroes): score Arena/Conquest formations from stat contributions"
```

---

## Task 5: Survival path + same-rarity power sanitize

**Worktree:** `sc-survival` — parallel with Task 6, after wave 1 is merged.

Two deliverables: threading contributions through the survival pipeline, and one approved gap from a second design doc (`docs/superpowers/specs/2026-08-03-arena-front-survival-opponent-models-design.md`), whose v1 is otherwise fully implemented on main.

**Files:**
- Modify: `ks/heroes/optimize/front_survival.py:44-63` (`sanitize_power`), `:66-73` (`roster_median_power`), `:100-132` (`hero_tau`, `formation_tau`)
- Modify: `ks/heroes/optimize/opponent_models.py:139-157` (`_gear_bonus_map`), `:160-197` (`_heuristic_offense`), `:202-216` (`_sanitized_power_map`), and the three builders
- Modify: `ks/heroes/optimize/survival_pipeline.py:40-64`, `:90-131`, `:134-157`, `:160-206`, `:209-303`, `:306-...`
- Modify: `ks/heroes/optimize/sensitivity.py` (forwarding + per-variant rebuild)
- Modify: `tests/test_heroes_pr26_bugbot.py` (rename-follow only)
- Test: `tests/test_heroes_front_survival.py`, `tests/test_heroes_sensitivity.py`

**Interfaces:**
- `sanitize_power(power, *, median_power, rarity=None, rarity_medians=None, max_abs=2_000_000, median_factor=20.0) -> float`
- `rarity_median_powers(heroes, *, max_abs=2_000_000) -> dict[str, float]`
- `hero_tau(hero, *, contribution=None, gear_pieces=None) -> float`
- `formation_tau(formation, heroes_by_name, gear_by_hero=None, contributions=None)`
- `slot_utilities(..., contributions: dict[str, StatContribution] | None = None)` replaces `gear_bonus_by_hero`
- `roster_pressure_scale(..., contributions=None)`, `evaluate_vs_foe(..., contributions=None)`, `_heuristic_offense(..., contributions=None)`
- `OpponentLineup` gains `contributions: dict[str, dict[str, Any]] | None = None`, emitted by `to_dict()`

**PR #26 invariants touched:** #1, #3, #4 (critically), #6.

### Part A — same-rarity power sanitize

Spec: *"if `power > 2_000_000` or `power > 20 × median(roster power)`, replace with **median of same-rarity peers** (or stars-scaled fallback)."* Main substitutes the whole-roster median, ignoring rarity. On the live roster the medians are epic 276,600 / legendary 337,100 / rare 193,308 against a roster median of 238,487 — so a corrupted legendary is replaced by a value ~41% too low.

- [ ] **Step 1: Write the failing sanitize tests**

Append to `tests/test_heroes_front_survival.py`:

```python
import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.front_survival import rarity_median_powers, sanitize_power


def _h(name: str, power: int | None, rarity: str | None) -> HeroRecord:
    return HeroRecord(name=name, power=power, rarity=rarity)


def test_rarity_median_powers_groups_by_rarity() -> None:
    medians = rarity_median_powers(
        [
            _h("a", 100_000, "epic"),
            _h("b", 300_000, "epic"),
            _h("c", 900_000, "legendary"),
        ]
    )
    assert medians["epic"] == pytest.approx(200_000.0)
    assert medians["legendary"] == pytest.approx(900_000.0)


def test_rarity_median_ignores_blowups_so_they_cannot_poison_their_own_bucket() -> None:
    medians = rarity_median_powers(
        [
            _h("a", 100_000, "epic"),
            _h("b", 300_000, "epic"),
            _h("bad", 9_000_000, "epic"),
        ]
    )
    assert medians["epic"] == pytest.approx(200_000.0)


def test_sanitize_prefers_same_rarity_median_over_roster_median() -> None:
    assert sanitize_power(
        9_000_000,
        median_power=238_487.0,
        rarity="legendary",
        rarity_medians={"legendary": 337_100.0, "epic": 276_600.0},
    ) == pytest.approx(337_100.0)


def test_sanitize_falls_back_to_roster_median_without_same_rarity_peers() -> None:
    assert sanitize_power(
        9_000_000,
        median_power=238_487.0,
        rarity="mythic",
        rarity_medians={"legendary": 337_100.0},
    ) == pytest.approx(238_487.0)


def test_sanitize_is_rarity_insensitive_for_plausible_power() -> None:
    assert sanitize_power(
        250_000,
        median_power=238_487.0,
        rarity="legendary",
        rarity_medians={"legendary": 337_100.0},
    ) == pytest.approx(250_000.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_heroes_front_survival.py -v`
Expected: FAIL — `ImportError: cannot import name 'rarity_median_powers'`

- [ ] **Step 3: Implement the rarity-aware sanitize**

Add to `ks/heroes/optimize/front_survival.py`, beside `roster_median_power`:

```python
def _median(values: list[float]) -> float:
    vals = sorted(values)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


def rarity_median_powers(
    heroes: list[HeroRecord],
    *,
    max_abs: int = 2_000_000,
) -> dict[str, float]:
    """Median scraped power per rarity, blow-ups excluded.

    Values above ``max_abs`` are dropped *before* the median is taken, so a
    corrupt reading cannot poison the very bucket used to replace it — with
    only two or three peers in a rarity that is a real risk, not a theoretical
    one.
    """
    by_rarity: dict[str, list[float]] = {}
    for hero in heroes:
        if not hero.power or hero.power <= 0 or hero.power > max_abs:
            continue
        key = (hero.rarity or "").strip().lower()
        if not key:
            continue
        by_rarity.setdefault(key, []).append(float(hero.power))
    return {k: _median(v) for k, v in by_rarity.items() if v}
```

Rewrite `roster_median_power` to delegate to `_median` (same signature and behaviour), then replace `sanitize_power` (`:44-63`) with:

```python
def sanitize_power(
    power: int | None,
    *,
    median_power: float,
    rarity: str | None = None,
    rarity_medians: dict[str, float] | None = None,
    max_abs: int = 2_000_000,
    median_factor: float = 20.0,
) -> float:
    """Drop OCR blow-ups before naive top-N selection / ILP scoring.

    An outlier is replaced by the median of its **same-rarity** peers when one
    is known — a legendary should not collapse to a roster median weighted by
    rares — and by the roster median otherwise.
    """
    if power is None or power <= 0:
        return 0.0
    if max_abs <= 0:
        raise ValueError(f"max_abs must be positive; got {max_abs}")
    if median_factor <= 0:
        raise ValueError(f"median_factor must be positive; got {median_factor}")

    def _replacement() -> float:
        peer = (rarity_medians or {}).get((rarity or "").strip().lower())
        if peer and peer > 0:
            return float(peer)
        return median_power

    p = float(power)
    if p > max_abs:
        return _replacement()
    if median_power > 0 and p > float(median_factor) * median_power:
        return _replacement()
    return p
```

- [ ] **Step 4: Feed rarity medians from both callers**

In `survival_pipeline.sanitize_hero_powers` (`:40-64`) and `opponent_models._sanitized_power_map` (`:202-216`), compute `rarity_medians = rarity_median_powers(heroes)` once alongside the existing median, and pass `rarity=h.rarity, rarity_medians=rarity_medians` into each `sanitize_power` call.

**Invariant 3:** `sanitize_hero_powers` must keep computing its medians over the same catalog-usable cohort it uses today — derive the rarity medians from that same filtered list, not from the unfiltered roster.

- [ ] **Step 5: Run and commit Part A**

Run: `uv run pytest tests/test_heroes_front_survival.py tests/test_heroes_pr26_bugbot.py -v`
Expected: PASS

```bash
git add ks/heroes/optimize/front_survival.py ks/heroes/optimize/survival_pipeline.py ks/heroes/optimize/opponent_models.py tests/test_heroes_front_survival.py
git commit -m "fix(heroes): sanitize OCR power against same-rarity peers"
```

### Part B — contribution-backed survival

- [ ] **Step 6: Write the failing tau tests**

Append to `tests/test_heroes_front_survival.py`:

```python
from ks.heroes.models import HeroStats
from ks.heroes.optimize.front_survival import formation_tau, hero_tau
from ks.heroes.optimize.stat_contributions import CONQUEST, Share, StatContribution


def _contrib(health: float, defense: float) -> StatContribution:
    return StatContribution(
        family=CONQUEST,
        estimated=True,
        skills_incomplete=False,
        power=Share(0.0, 0.0, 0.0),
        stats={
            "Hero Health": Share(health * 0.6, health * 0.1, health * 0.3),
            "Hero Defense": Share(defense * 0.6, defense * 0.1, defense * 0.3),
        },
    )


def test_hero_tau_uses_contribution_totals() -> None:
    hero = HeroRecord(
        name="A", stats=HeroStats(conquest={"Hero Health": 100, "Hero Defense": 10})
    )
    assert hero_tau(hero, contribution=_contrib(500.0, 50.0)) == pytest.approx(
        500.0 * 50.0
    )


def test_hero_tau_falls_back_to_scrape_without_contribution() -> None:
    hero = HeroRecord(
        name="A", stats=HeroStats(conquest={"Hero Health": 100, "Hero Defense": 10})
    )
    assert hero_tau(hero) == pytest.approx(100.0 * 10.0)


def test_hero_tau_never_below_one() -> None:
    assert hero_tau(HeroRecord(name="A"), contribution=_contrib(0.0, 0.0)) >= 1.0


def test_formation_tau_splits_front_and_back_from_contributions() -> None:
    heroes = {
        n: HeroRecord(
            name=n, stats=HeroStats(conquest={"Hero Health": 10, "Hero Defense": 2})
        )
        for n in ("a", "b", "c", "d", "e")
    }
    formation = {"F1": "a", "F2": "b", "B1": "c", "B2": "d", "B3": "e"}
    contributions = {n: _contrib(100.0, 10.0) for n in heroes}
    tau_f, tau_b, by_hero = formation_tau(
        formation, heroes, None, contributions=contributions
    )
    assert tau_f == pytest.approx(2 * 100.0 * 10.0)
    assert tau_b == pytest.approx(3 * 100.0 * 10.0)
    assert set(by_hero) == set(heroes)
```

- [ ] **Step 7: Rewrite `hero_tau` / `formation_tau`**

Replace `front_survival.py:100-132` with:

```python
def _share_total(contribution: "StatContribution", label: str) -> float:
    share = contribution.stats.get(label)
    return share.total if share is not None else 0.0


def hero_tau(
    hero: HeroRecord,
    *,
    contribution: "StatContribution | None" = None,
    gear_pieces: Mapping[str, GearRecord] | None = None,
) -> float:
    """Toughness proxy: health × defense, with expedition gear health on top.

    With a ``contribution`` the health/defense totals already carry the hero +
    skills + gear conquest flats. The expedition health fraction from
    chest/gloves is still applied as a multiplier because it is a percent buff
    on a different axis, not one of those flats.
    """
    if contribution is not None:
        hp = max(1.0, _share_total(contribution, "Hero Health"))
        defense = max(1.0, _share_total(contribution, "Hero Defense"))
    else:
        hp = float(max(1, conquest_stat(hero, "Hero Health")))
        defense = float(max(1, conquest_stat(hero, "Hero Defense")))
    return hp * defense * (1.0 + gear_health_bonus(gear_pieces))


def formation_tau(
    formation: Mapping[str, str],
    heroes_by_name: Mapping[str, HeroRecord],
    gear_by_hero: Mapping[str, Mapping[str, GearRecord]] | None = None,
    contributions: Mapping[str, "StatContribution"] | None = None,
) -> tuple[float, float, dict[str, float]]:
    gear_by_hero = gear_by_hero or {}
    contributions = contributions or {}
    by_hero: dict[str, float] = {}
    tau_f = 0.0
    tau_b = 0.0
    for slot, name in formation.items():
        hero = heroes_by_name.get(name)
        if hero is None:
            raise ValueError(
                f"formation references unknown hero {name!r} in slot {slot!r}"
            )
        tau = hero_tau(
            hero,
            contribution=contributions.get(name),
            gear_pieces=gear_by_hero.get(name),
        )
        by_hero[name] = tau
        if slot in FRONT:
            tau_f += tau
        elif slot in BACK:
            tau_b += tau
    return tau_f, tau_b, by_hero
```

Change the typing import to `from typing import TYPE_CHECKING, Any, Mapping` and add:

```python
if TYPE_CHECKING:  # pragma: no cover
    from ks.heroes.optimize.stat_contributions import StatContribution
```

**Callers must keep passing `gear_by_hero` even when passing `contributions`** — the conquest flats and the expedition health percent are different buffs and both count.

- [ ] **Step 8: Rewire `opponent_models.py`**

Replace `_gear_bonus_map` (`:139-157`) with `_contribution_map`, preserving invariant 1:

```python
def _contribution_map(
    formation: dict[str, str],
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    gear_asg: dict[str, dict[str, GearRecord]],
    *,
    power_by_name: dict[str, float] | None = None,
) -> dict[str, StatContribution]:
    """Conquest contributions from the foe's *already assigned* pieces.

    Must not flatten pieces back into a pool and re-assign by roster power —
    that clobbers explicit exclusive assignments (PR #26 invariant 1).
    """
    from ks.heroes.optimize.combat_formation import contributions_from_assignment

    selected = [formation[s] for s in ALL_SLOTS if s in formation]
    scoped = {name: gear_asg.get(name, {}) for name in selected}
    powers = {
        name: int(round(v)) if v else None
        for name, v in (power_by_name or {}).items()
    }
    return contributions_from_assignment(
        scoped,
        catalog=catalog,
        heroes_by_name={h.name: h for h in heroes},
        power_by_name=powers,
        family=CONQUEST,
    )
```

Replace `_heuristic_offense`'s `gear_bonus_by_hero` parameter with `contributions: dict[str, StatContribution] | None = None`, update its default `score_fn` closure to the new protocol, and pass `contribution=(contributions or {}).get(name)` in the score call.

In all three builders (`build_naive_max_power`, `build_troop_balanced_naive`, `opponent_from_formation`), replace the `_gear_bonus_map(...)` call with `_contribution_map(...)` and pass `contributions=contributions` to `_heuristic_offense`. **Invariant 6:** `opponent_from_formation` must keep honouring an explicitly passed `gear_assignment`.

Add `contributions: dict[str, dict[str, Any]] | None = None` to `OpponentLineup`, emit it from `to_dict()`, and pass `contributions={n: c.to_dict() for n, c in contributions.items()}` at each construction.

Add: `from ks.heroes.optimize.stat_contributions import CONQUEST, StatContribution`

- [ ] **Step 9: Rewire `survival_pipeline.py`**

- `slot_utilities` (`:90-131`): replace `gear_bonus_by_hero` with `contributions: dict[str, StatContribution] | None = None`; pass `contribution=(contributions or {}).get(name)` to `base_score_fn`. **Invariant 4:** the contributions passed in must be the gear-bearing ones so `U_front`/`U_back` still include the gear signal. Do not pass bare contributions here.
- `roster_pressure_scale` (`:134-157`): add the same keyword; pass `contribution=` to both `base_score_fn` and `hero_tau`.
- `evaluate_vs_foe` (`:160-206`): add `contributions=None`; forward to `formation_tau(..., contributions=contributions)` and `slot_utilities(..., contributions=contributions)`.
- `build_self_play_foes` (`:209-303`): update the default `score_fn` closure to the new protocol.
- `attach_survival` (`:306-...`): after `our_gear = gear_maps_for_formation(...)`, build our contributions once and thread them everywhere:

```python
    from ks.heroes.optimize.combat_formation import contributions_from_assignment

    our_contributions = contributions_from_assignment(
        {name: our_gear.get(name, {}) for name in result.formation.values()},
        catalog=catalog,
        heroes_by_name={h.name: h for h in heroes},
        power_by_name=power_by_name,
        family=CONQUEST,
    )
```

Pass `contributions=our_contributions` to `evaluate_vs_foe`, `formation_tau`, `slot_utilities` and `build_sensitivity`. Add `"stat_family": CONQUEST` and `"contributions": {n: c.to_dict() for n, c in our_contributions.items()}` to the `survival["our"]` dict — **additive keys only**, so `tests/test_heroes_survival_api.py` keeps passing.

- [ ] **Step 10: Forward through `sensitivity.py`**

Add `contributions: dict[str, StatContribution] | None = None` to `build_sensitivity` and forward to every `evaluate_vs_foe` call.

**Critical:** each variant re-assigns gear via `gear_maps_for_formation`, so each variant must rebuild its **own** contributions from *its* gear map with `contributions_from_assignment`. A variant that reused the baseline's contributions would score every gear order identically and silently flatten the whole sensitivity table to zero deltas — which `test_heroes_survival_api.py` would not catch, since it only pins `baseline.delta_score_eff == 0.0`.

Update `tests/test_heroes_sensitivity.py`'s `_base_score` stub (`:43-44`):

```python
def _base_score(hero, entry, roles, *, effective_power, contribution):
    return float(effective_power or 0) / 1000.0
```

- [ ] **Step 11: Follow the renames in `tests/test_heroes_pr26_bugbot.py`**

That file imports `_provisional_gear_bonus` and `gear_bonus_from_assignment` and calls `slot_utilities(..., gear_bonus_by_hero=...)`. Update the imports and call sites to the new names, and adapt each assertion to compare contribution-derived strength instead of a bare float. **The six invariants must keep their original meaning.** If any cannot be expressed against the new API, stop and report it rather than weakening the assertion.

- [ ] **Step 12: Run the tests**

Run: `uv run pytest tests/test_heroes_front_survival.py tests/test_heroes_sensitivity.py tests/test_heroes_pr26_bugbot.py tests/test_heroes_survival_api.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_conquest.py tests/test_heroes_optimize_hardening.py -v`
Expected: PASS

- [ ] **Step 13: Full suite, then commit**

Run: `uv run pytest -q`
Expected: PASS except the known pre-existing gear_assign failure and the spend_xp / UI suites owned by Tasks 6-8.

```bash
git add ks/heroes/optimize/ tests/
git commit -m "feat(heroes): base survival and foe models on stat contributions"
```

---

## Task 6: Gear XP spend

**Worktree:** `sc-spendxp` — parallel with Task 5.

**Files:**
- Modify: `ks/heroes/optimize/spend_xp.py:120-148` (`_arena` summary), `:182-220` (both `_event` summaries)
- Test: `tests/test_heroes_spend_xp.py`

**Interfaces:**
- Consumes `RecommendResult.stat_family` / `.formation_totals` (Task 3) and `ArenaResult.stat_family` / `.formation_totals` / `.contributions` (Task 4).
- Produces: every summary dict gains `"stat_family": str` and `"formation_totals": dict | None`; the arena summary also gains `"contributions"`. These surface through `SpendResult.to_dict()` under `baseline_summary` / `best_summary`, and thus through `POST /api/optimize/gear-xp`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_heroes_spend_xp.py` (it already defines `_piece`):

```python
from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.optimize.spend_xp import build_event_utility

_ROOT = Path(__file__).resolve().parents[1]

# Names must exist in config/hero_catalog.yaml so the real catalog resolves;
# optimize_arena drops heroes the catalog does not know and needs five.
_ROSTER = [
    ("Helga", "infantry", "legendary", 3, 500_000),
    ("Howard", "infantry", "epic", 3, 390_000),
    ("Jabel", "cavalry", "legendary", 4, 650_000),
    ("Chenko", "cavalry", "epic", 3, 400_000),
    ("Saul", "archer", "legendary", 2, 250_000),
    ("Diana", "archer", "epic", 3, 450_000),
    ("Gordon", "cavalry", "epic", 2, 230_000),
]


def _heroes() -> list[HeroRecord]:
    return [
        HeroRecord(
            name=name,
            troop_type=troop,
            rarity=rarity,
            stars=stars,
            pellets=0,
            power=power,
            escorts=5,
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for name, troop, rarity, stars, power in _ROSTER
    ]


def _gear() -> list[GearRecord]:
    return [
        _piece(f"{troop}-{slot}", level=20, troop=troop, slot=slot)
        for troop in ("infantry", "cavalry", "archers")
        for slot in ("helmet", "chest", "gloves", "boots")
    ]


def test_arena_utility_summary_carries_contributions() -> None:
    utility = build_event_utility("arena_attack", _heroes(), config_root=_ROOT)
    _util, summary = utility(_gear())
    assert summary["stat_family"] == "conquest"
    totals = summary["formation_totals"]
    assert set(totals["power"]) == {"hero", "skills", "gear", "total"}
    assert totals["power"]["total"] == pytest.approx(
        totals["power"]["hero"] + totals["power"]["skills"] + totals["power"]["gear"]
    )


def test_event_utility_summary_carries_contributions() -> None:
    utility = build_event_utility("swordland", _heroes(), config_root=_ROOT)
    _util, summary = utility(_gear())
    assert summary["stat_family"] == "expedition"
    assert summary["formation_totals"] is not None


def test_levelling_gear_raises_gear_share_of_totals() -> None:
    utility = build_event_utility("arena_attack", _heroes(), config_root=_ROOT)
    base_gear = _gear()
    _u0, s0 = utility(base_gear)
    bumped = apply_levels(
        base_gear, {p.piece_id: (p.enhancement_level or 0) + 20 for p in base_gear}
    )
    _u1, s1 = utility(bumped)
    assert (
        s1["formation_totals"]["power"]["gear"]
        > s0["formation_totals"]["power"]["gear"]
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_heroes_spend_xp.py -v`
Expected: FAIL — `KeyError: 'stat_family'`

- [ ] **Step 3: Add the keys to the arena summary**

In `build_event_utility`'s `_arena` closure, add to the returned summary dict:

```python
                "stat_family": result.stat_family,
                "formation_totals": result.formation_totals,
                "contributions": result.contributions,
```

- [ ] **Step 4: Add the keys to both event summaries**

In the `_event` closure, add to the pinned-mode summary:

```python
                "stat_family": result.stat_family,
                "formation_totals": result.formation_totals,
```

and to the best-of-all-modes summary, using `best`:

```python
            "stat_family": best.stat_family,
            "formation_totals": best.formation_totals,
```

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/test_heroes_spend_xp.py tests/test_heroes_xp_ladder.py -v`
Expected: PASS

Run: `uv run pytest -q`
Expected: PASS except the known pre-existing gear_assign failure and the UI suites owned by Tasks 7-8.

```bash
git add ks/heroes/optimize/spend_xp.py tests/test_heroes_spend_xp.py
git commit -m "feat(heroes): report contribution totals from gear XP utility"
```

---

## Task 7: API payload

**Worktree:** `sc-api` — parallel with Task 8.

**Files:**
- Modify: `ks/heroes/ui/optimize_run.py:29-78` (`_event_bundle`), `:81-82` (`_section_error`), `:85-100` (`_formation_error`), and the four `_section_error` / four `_formation_error` call sites
- Test: `tests/test_heroes_optimize_ui.py`

**Interfaces (FROZEN CONTRACT — Task 8 renders exactly this):**

Every Sword/Bear **mode row** (`bundle["sword"]["modes"][<mode>]`) and every **formation row** (`bundle["arena"]["attack"]`, `bundle["arena"]["defense"]`, `bundle["conquest"]`) carries:

```json
{
  "stat_family": "conquest",
  "formation_totals": {
    "family": "conquest",
    "estimated": true,
    "skills_incomplete": false,
    "power": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 },
    "stats": {
      "Hero Attack": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 }
    }
  },
  "contributions": {
    "Howard": {
      "family": "conquest",
      "estimated": true,
      "skills_incomplete": false,
      "power": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 },
      "stats": { "Hero Attack": { "hero": 0.0, "skills": 0.0, "gear": 0.0, "total": 0.0 } }
    }
  }
}
```

Rules the UI may rely on:
- `stat_family` is **always present** on every row and every section, including error rows — the UI never branches on its absence.
- `formation_totals` and `contributions` are `null` when the row is not `Optimal`.
- Sword/Bear rows keep per-hero contributions inline on each `heroes[]` row (from Task 3); Task 7 additionally normalises them into the same top-level `contributions` name→payload map so all four screens share one shape.
- Sections `bundle["sword"]` and `bundle["bear"]` also carry a section-level `stat_family`. `bundle["arena"]` is a plain `{attack, defense}` mapping and gets no section-level key.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_heroes_optimize_ui.py` (it already defines `ROOT` and `_seed_roster`):

```python
from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroStats
from ks.heroes.ui.optimize_run import run_optimize_bundle

_SHARE_KEYS = {"hero", "skills", "gear", "total"}


def _contrib_heroes() -> list[HeroRecord]:
    rows = [
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
    ]
    return [
        HeroRecord(
            name=name, troop_type=troop, rarity=rarity, stars=stars, pellets=0,
            power=power, escorts=5, roster_page=0, roster_index=i, scraped_at="t",
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for i, (name, troop, rarity, stars, power) in enumerate(rows)
    ]


def _contrib_gear() -> list[GearRecord]:
    prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}
    out: list[GearRecord] = []
    for troop in ("infantry", "cavalry", "archers"):
        for slot in ("helmet", "chest", "gloves", "boots"):
            stat = "Lethality" if slot in ("helmet", "boots") else "Health"
            out.append(
                GearRecord(
                    piece_id=f"{troop}-{slot}", name=f"{troop} {slot}",
                    troop_type=troop, slot=slot, rarity="mythic",
                    enhancement_level=40, power=60_000,
                    stats=GearStats(
                        conquest={"Hero Attack": 300, "Hero Health": 1500},
                        expedition={f"{prefix[troop]} {stat}": 32.0},
                    ),
                )
            )
    return out


def _assert_contribution(payload: dict) -> None:
    assert payload["family"] in {"conquest", "expedition"}
    assert payload["estimated"] is True
    assert set(payload["power"]) == _SHARE_KEYS
    assert payload["power"]["total"] == pytest.approx(
        payload["power"]["hero"] + payload["power"]["skills"] + payload["power"]["gear"]
    )
    for share in payload["stats"].values():
        assert set(share) == _SHARE_KEYS
        assert share["hero"] >= 0
        assert share["skills"] >= 0
        assert share["gear"] >= 0
        assert share["total"] == pytest.approx(
            share["hero"] + share["skills"] + share["gear"]
        )


def test_bundle_event_sections_carry_expedition_contributions() -> None:
    bundle = run_optimize_bundle(
        _contrib_heroes(), gear=_contrib_gear(), config_root=ROOT
    )
    for section in ("sword", "bear"):
        assert bundle[section]["stat_family"] == "expedition"
        for row in bundle[section]["modes"].values():
            assert row["stat_family"] == "expedition"
            _assert_contribution(row["formation_totals"])
            assert row["contributions"]
            for contrib in row["contributions"].values():
                _assert_contribution(contrib)


def test_bundle_combat_sections_carry_conquest_contributions() -> None:
    bundle = run_optimize_bundle(
        _contrib_heroes(), gear=_contrib_gear(), config_root=ROOT
    )
    for row in (bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]):
        if row.get("status") != "Optimal":
            continue
        assert row["stat_family"] == "conquest"
        _assert_contribution(row["formation_totals"])
        for contrib in row["contributions"].values():
            _assert_contribution(contrib)


def test_error_rows_still_declare_stat_family() -> None:
    # An empty roster makes every section infeasible; the shape must still hold.
    bundle = run_optimize_bundle([], gear=None, config_root=ROOT)
    for row in (bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]):
        assert row["stat_family"] == "conquest"
        assert row["formation_totals"] is None
        assert row["contributions"] is None
    for section in ("sword", "bear"):
        assert bundle[section]["stat_family"] == "expedition"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_heroes_optimize_ui.py -v`
Expected: FAIL — `KeyError: 'stat_family'`

- [ ] **Step 3: Normalise the event bundle rows**

In `_event_bundle`, replace `modes[mode] = result.to_dict()` with:

```python
            payload = result.to_dict()
            payload["contributions"] = {
                row["name"]: row["contributions"]
                for row in payload.get("heroes") or []
                if row.get("name") and row.get("contributions")
            } or None
            modes[mode] = payload
```

and add `stat_family` to the section `out` dict (`:70-75`):

```python
    out: dict[str, Any] = {
        "label": label,
        "event": event.name,
        "status": "ok",
        "stat_family": family_for_event(event.name),
        "modes": modes,
    }
```

Add the import: `from ks.heroes.optimize.stat_contributions import family_for_event`

- [ ] **Step 4: Give the failure shapes the same keys**

Update `_section_error` (`:81-82`):

```python
def _section_error(label: str, message: str, *, stat_family: str) -> dict[str, Any]:
    return {
        "label": label,
        "modes": {},
        "status": "Error",
        "error": message,
        "stat_family": stat_family,
    }
```

and pass `stat_family="expedition"` at all four call sites (`:183`, `:187`, `:203`, `:207`).

Update `_formation_error` (`:85-100`) so arena/conquest failures declare the same three keys:

```python
def _formation_error(message: str, **identity: str) -> dict[str, Any]:
    return {
        **identity,
        "status": "Error",
        "formation": {},
        "heroes": [],
        "score": None,
        "reasons": {},
        "error": message,
        "stat_family": "conquest",
        "formation_totals": None,
        "contributions": None,
    }
```

**Note:** an *infeasible* (rather than errored) arena/conquest solve returns `CombatFormationResult.to_dict()` / `ArenaResult.to_dict()` with the Task 4 dataclass defaults — `stat_family="conquest"`, `formation_totals=None`, `contributions=None` — so no extra branch is needed for that path. Only the `except` branches need `_formation_error`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_heroes_optimize_ui.py tests/test_heroes_survival_api.py -v`
Expected: PASS

- [ ] **Step 6: Full suite**

Run: `uv run pytest -q`
Expected: PASS except the known pre-existing gear_assign failure.

- [ ] **Step 7: Commit**

```bash
git add ks/heroes/ui/optimize_run.py tests/test_heroes_optimize_ui.py
git commit -m "feat(heroes-ui): expose stat contributions on the optimize API"
```

---

## Task 8: Event lineups UI (Apple-light design system)

**Worktree:** `sc-ui` — parallel with Task 7, against Task 7's frozen contract.

**No template change is needed.** `#board` and `#gear-modal-body` are both rewritten wholesale by JS, so this task touches only the script, the stylesheet and the JS harness.

**Files:**
- Modify: `ks/heroes/ui/static/optimiser_events.js` (helpers + `renderBoard` + `openHeroSheet`)
- Modify: `ks/heroes/ui/static/app.css` (two new rule blocks)
- Modify: `tests/js/optimiser_events_harness.js` (new named checks)
- Modify: `tests/test_heroes_optimiser_events_js.py` (assert the new checks)

**Design constraints — this UI has a house style; match it, do not invent one:**
- `app.css` header: *"KS heroes UI — Apple light theme. Phone-first; no dark variant by design."* Do **not** add a dark-mode block.
- Reuse the existing token vocabulary only: `--panel`, `--canvas`, `--border`, `--text`, `--muted`, `--muted-soft`, `--accent`, `--radius-sm`, `--tap`. Borders are uniformly `1px solid var(--border)`.
- **Never** use `--ok` / `--err` as text colour — `app.css:14-16` documents that both fail contrast on white; use `--ok-text` / `--err-text` when a state is spelled out in words.
- Numbers use `font-variant-numeric: tabular-nums`, as `.board-meta`, `.mode-score`, `.gear-meta` and `.fact-v` all do.
- Type scale in play: `0.85rem` table text, `0.82rem`/`0.8rem` meta, `0.75rem`/`0.7rem`/`0.68rem` uppercase label text.
- **Precedent for the compact strip:** `.fact` / `.fact-k` / `.fact-v` (`app.css:1045-1063`) — a bordered `--radius-sm` chip, uppercase muted label above a tabular-nums value, laid out on the `repeat(auto-fill, minmax(9rem, 1fr))` grid that `.gear-grid` and `.mode-chips` also use.
- **Precedent for the table:** `.stat-table` / `.skill-table` (`app.css:1073-1100`) — `border-collapse: collapse`, `0.85rem`, `0.35rem 0.4rem` cell padding, `1px solid var(--border)` row dividers only (no vertical rules), muted 600-weight `<th>`, preceded by an `<h3 class="section-title">`. Follow this, **not** `.data-table` (that one is the heavy sortable/sticky inventory grid).
- Text discipline (documented at the top of `optimiser_events.js`): anything from the API reaches the DOM via `textContent` or through `esc()`. Hero names and stat labels come from OCR and config — treat both as untrusted.

**Interfaces:**
- Consumes Task 7's frozen contract.
- Produces two JS helpers — `renderContributionStrip(row)` (board) and `renderContributionTable(row)` (hero sheet) — plus `fmtShare(n, family)`.

- [ ] **Step 1: Add the failing harness checks**

In `tests/js/optimiser_events_harness.js`, after the existing board checks, add checks that exercise the new rendering. Follow the harness's own `check(name, ok, detail)` / `record(key, value)` idiom and give every check a unique name (a test asserts uniqueness):

```js
  // --- stat contributions --------------------------------------------------
  selectEvent("conquest");
  var conquestBoard = boardEl.innerHTML;
  record("conquest_board_html", conquestBoard);
  check(
    "the board carries a stat contribution strip",
    conquestBoard.indexOf("contrib-strip") !== -1,
    conquestBoard.slice(0, 400)
  );
  check(
    "the strip names the stat family",
    conquestBoard.toLowerCase().indexOf("conquest") !== -1,
    conquestBoard.slice(0, 400)
  );
  check(
    "the strip splits power into hero, skills and gear",
    ["hero", "skills", "gear"].every(function (k) {
      return conquestBoard.toLowerCase().indexOf(k) !== -1;
    }),
    conquestBoard.slice(0, 400)
  );

  openFirstHero();
  var sheet = modalBody.innerHTML;
  record("conquest_sheet_html", sheet);
  check(
    "the hero sheet carries a contribution table",
    sheet.indexOf("contrib-table") !== -1,
    sheet.slice(0, 400)
  );
  check(
    "the contribution table has a row per placed hero",
    (sheet.match(/<tr/g) || []).length >= 2,
    sheet.slice(0, 400)
  );
  check(
    "the contribution table totals the formation",
    sheet.toLowerCase().indexOf("formation") !== -1,
    sheet.slice(0, 400)
  );
  check(
    "an estimated split says so",
    sheet.toLowerCase().indexOf("estimated") !== -1,
    sheet.slice(0, 400)
  );
```

The harness's existing fixture bundle must gain `stat_family`, `formation_totals` and `contributions` on its conquest and sword rows, matching Task 7's contract exactly. Use small round numbers so the checks read clearly. If the harness has no `selectEvent` / `openFirstHero` helper, add one next to whatever it already uses to drive the board, and name it in the same style as the surrounding code.

- [ ] **Step 2: Assert the new checks from Python**

Append to `tests/test_heroes_optimiser_events_js.py`:

```python
def test_the_board_shows_where_strength_came_from(js_run: dict) -> None:
    """Design decision C: formation totals on the board, per-hero in the sheet."""
    _assert_ran(
        js_run,
        [
            "the board carries a stat contribution strip",
            "the strip names the stat family",
            "the strip splits power into hero, skills and gear",
        ],
    )
    board = js_run["data"]["conquest_board_html"]
    assert "contrib-strip" in board


def test_the_hero_sheet_breaks_the_split_down_per_hero(js_run: dict) -> None:
    _assert_ran(
        js_run,
        [
            "the hero sheet carries a contribution table",
            "the contribution table has a row per placed hero",
            "the contribution table totals the formation",
            "an estimated split says so",
        ],
    )
    sheet = js_run["data"]["conquest_sheet_html"]
    assert "contrib-table" in sheet
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_heroes_optimiser_events_js.py -v`
Expected: FAIL — the new checks report `ok: false` (the classes are not emitted yet). If the whole module skips, no JS engine is on `PATH`; install one or note the skip in your report — do not mark the task done on a skipped suite.

- [ ] **Step 4: Add the JS helpers**

Insert into `ks/heroes/ui/static/optimiser_events.js`, immediately before `function renderBoard(`:

```js
  /* --- stat contributions ---------------------------------------------------
   *
   * Every optimiser row carries the same three keys (see optimize_run.py):
   * `stat_family`, `formation_totals` and `contributions`. Conquest shares are
   * flat stat points and sum; expedition shares are percent points and also
   * sum — which is why the formatter takes the family rather than guessing
   * from magnitude.
   */

  function fmtShare(n, family) {
    if (n == null || !Number.isFinite(Number(n))) return "—";
    if (family === "expedition") return Number(n).toFixed(1) + "%";
    return Math.round(Number(n)).toLocaleString("en-US");
  }

  /** The row's formation-level split, or null when the row is not Optimal. */
  function totalsOf(row) {
    var totals = row && row.formation_totals;
    return totals && totals.power ? totals : null;
  }

  /** Chips: the power split, then the largest stat totals for that family. */
  function renderContributionStrip(row) {
    var totals = totalsOf(row);
    if (!totals) return "";
    var family = row.stat_family || totals.family || "conquest";
    var p = totals.power;
    var facts = [
      ["power", fmtShare(p.total, "conquest")],
      ["from hero", fmtShare(p.hero, "conquest")],
      ["from skills", fmtShare(p.skills, "conquest")],
      ["from gear", fmtShare(p.gear, "conquest")]
    ];
    Object.keys(totals.stats || {})
      .map(function (label) {
        return [label, totals.stats[label]];
      })
      .filter(function (pair) {
        return pair[1] && pair[1].total > 0;
      })
      .sort(function (a, b) {
        return b[1].total - a[1].total;
      })
      .slice(0, 3)
      .forEach(function (pair) {
        facts.push([pair[0], fmtShare(pair[1].total, family)]);
      });
    var chips = facts
      .map(function (pair) {
        return (
          '<div class="fact"><div class="fact-k">' + esc(pair[0]) +
          '</div><div class="fact-v">' + esc(pair[1]) + "</div></div>"
        );
      })
      .join("");
    var flags = [];
    if (totals.estimated) flags.push("estimated");
    if (totals.skills_incomplete) flags.push("skills partial");
    var note = flags.length
      ? '<p class="contrib-note">' + esc(family + " · " + flags.join(" · ")) + "</p>"
      : '<p class="contrib-note">' + esc(family) + "</p>";
    return '<div class="contrib-strip">' + chips + "</div>" + note;
  }

  /** One row per placed hero, plus a formation total row. */
  function renderContributionTable(row) {
    var contributions = (row && row.contributions) || null;
    if (!contributions) return "";
    var family = row.stat_family || "conquest";
    var names = orderedHeroNames(row).filter(function (n) {
      return contributions[n];
    });
    if (!names.length) return "";

    var labels = [];
    names.forEach(function (name) {
      Object.keys(contributions[name].stats || {}).forEach(function (label) {
        if (labels.indexOf(label) === -1) labels.push(label);
      });
    });

    function split(share, fam) {
      if (!share) return "—";
      return (
        esc(fmtShare(share.total, fam)) +
        '<br><span class="contrib-split">' +
        esc(
          fmtShare(share.hero, fam) + " · " +
          fmtShare(share.skills, fam) + " · " +
          fmtShare(share.gear, fam)
        ) +
        "</span>"
      );
    }

    var head =
      "<tr><th>hero</th><th>power</th>" +
      labels
        .map(function (l) {
          return "<th>" + esc(l) + "</th>";
        })
        .join("") +
      "</tr>";
    var body = names
      .map(function (name) {
        var c = contributions[name];
        return (
          "<tr><td>" + esc(name) + "</td>" +
          "<td>" + split(c.power, "conquest") + "</td>" +
          labels
            .map(function (l) {
              return "<td>" + split((c.stats || {})[l], family) + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");
    var totals = totalsOf(row);
    var totalRow = totals
      ? '<tr class="contrib-total"><td>formation</td><td>' +
        esc(fmtShare(totals.power.total, "conquest")) + "</td>" +
        labels
          .map(function (l) {
            var share = (totals.stats || {})[l];
            return "<td>" + esc(share ? fmtShare(share.total, family) : "—") + "</td>";
          })
          .join("") +
        "</tr>"
      : "";
    return (
      '<h3 class="section-title">Stat contributions · ' + esc(family) + "</h3>" +
      '<p class="contrib-note">each cell: total, then hero · skills · gear</p>' +
      '<div class="table-scroll"><table class="contrib-table"><thead>' +
      head + "</thead><tbody>" + body + totalRow + "</tbody></table></div>"
    );
  }
```

- [ ] **Step 5: Call them from the board and the sheet**

In `renderBoard`, after the `appendText("p", "board-meta", ...)` call and before the formation rows, append the strip. `appendText` sets `textContent`, so the strip needs its own element:

```js
    var strip = renderContributionStrip(row);
    if (strip) {
      var stripEl = document.createElement("div");
      stripEl.innerHTML = strip;
      boardEl.appendChild(stripEl);
    }
```

In `openHeroSheet`, extend the body assembly so the table sits between the why-block and the gear grid:

```js
    modalBody.innerHTML =
      renderWhy(explain) +
      renderContributionTable(entry.row) +
      renderGearGrid(assignment[name]);
```

- [ ] **Step 6: Add the styles**

Append to `ks/heroes/ui/static/app.css`, next to the other events-board rules (after the `.gear-*` block):

```css
/* --- stat contributions ---------------------------------------------------
   The board strip reuses .fact/.fact-k/.fact-v chips on the same auto-fill
   grid as .gear-grid and .mode-chips; the sheet table follows .stat-table's
   compact idiom rather than .data-table's sortable inventory grid. */

.contrib-strip {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(7rem, 1fr));
  gap: 0.4rem;
  margin: 0 0 0.35rem;
}

.contrib-note {
  margin: 0 0 0.9rem;
  color: var(--muted-soft);
  font-size: 0.72rem;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

/* A wide formation can carry six stat columns; let it scroll rather than
   squeeze the sheet, which is only ~22rem on a 390px viewport. */
.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

table.contrib-table {
  width: 100%;
  margin-bottom: 0.5rem;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.contrib-table th,
.contrib-table td {
  padding: 0.35rem 0.4rem;
  border-bottom: 1px solid var(--border);
  text-align: right;
  vertical-align: top;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.contrib-table th:first-child,
.contrib-table td:first-child {
  text-align: left;
}

.contrib-table th {
  color: var(--muted);
  font-weight: 600;
  font-size: 0.7rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.contrib-table tbody tr:last-child td {
  border-bottom: none;
}

.contrib-table tr.contrib-total td {
  font-weight: 600;
}

.contrib-split {
  color: var(--muted-soft);
  font-size: 0.72rem;
}
```

- [ ] **Step 7: Run the JS tests**

Run: `uv run pytest tests/test_heroes_optimiser_events_js.py -v`
Expected: PASS

- [ ] **Step 8: Run the UI suites**

Run: `uv run pytest tests/test_heroes_optimize_ui.py tests/test_heroes_optimiser_gear_xp_js.py tests/test_heroes_roster_ui.py -v`
Expected: PASS

- [ ] **Step 9: See it in the real app**

Run:

```bash
uv run python -m ks.heroes.cli ui --heroes data/heroes/full-run --gear data/gear/full-run
```

Open `http://127.0.0.1:8000/optimiser/events`. On each of the four event segments confirm: the board shows a chip strip with power split into hero / skills / gear plus the top stats for that family (flat numbers for Arena/Conquest, percents for Swordland/Bear); tapping a hero opens the sheet with a "Stat contributions" table, one row per placed hero, a formation total row, and `hero · skills · gear` beneath each total. Check it at a 390px-wide viewport — the table should scroll inside its own container rather than widening the sheet. Stop the server when done.

- [ ] **Step 10: Commit**

```bash
git add ks/heroes/ui/static/optimiser_events.js ks/heroes/ui/static/app.css tests/js/optimiser_events_harness.js tests/test_heroes_optimiser_events_js.py
git commit -m "feat(heroes-ui): show stat contributions on the lineup board and hero sheet"
```

---

## Task 9: Cross-optimiser wiring regression suite

**Worktree:** base worktree, after every wave is merged.

**Files:**
- Create: `tests/test_heroes_optimize_contributions_wiring.py`

- [ ] **Step 1: Write the test**

```python
"""Every optimiser surface derives strength from stat contributions.

Wiring + invariant assertions, deliberately not frozen score values — the
whole point of the rewrite is that the numbers changed. See the plan's
"Measured calibration note" for the size of that change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.models import HeroRecord, HeroStats
from ks.heroes.ui.optimize_run import run_optimize_bundle

_ROOT = Path(__file__).resolve().parents[1]
_SHARE_KEYS = {"hero", "skills", "gear", "total"}


def _heroes() -> list[HeroRecord]:
    rows = [
        ("Helga", "infantry", "legendary", 3, 500_000),
        ("Howard", "infantry", "epic", 3, 390_000),
        ("Jabel", "cavalry", "legendary", 4, 650_000),
        ("Chenko", "cavalry", "epic", 3, 400_000),
        ("Saul", "archer", "legendary", 2, 250_000),
        ("Diana", "archer", "epic", 3, 450_000),
        ("Gordon", "cavalry", "epic", 2, 230_000),
    ]
    return [
        HeroRecord(
            name=name, troop_type=troop, rarity=rarity, stars=stars, pellets=0,
            power=power, escorts=5, roster_page=0, roster_index=i, scraped_at="t",
            stats=HeroStats(
                conquest={
                    "Hero Attack": power // 300,
                    "Hero Defense": power // 350,
                    "Hero Health": power // 40,
                    "Escort Attack": power // 900,
                    "Escort Defense": power // 1050,
                    "Escort Health": power // 120,
                }
            ),
        )
        for i, (name, troop, rarity, stars, power) in enumerate(rows)
    ]


def _gear() -> list[GearRecord]:
    prefix = {"infantry": "Infantry", "cavalry": "Cavalry", "archers": "Archer"}
    out: list[GearRecord] = []
    for troop in ("infantry", "cavalry", "archers"):
        for slot in ("helmet", "chest", "gloves", "boots"):
            stat = "Lethality" if slot in ("helmet", "boots") else "Health"
            out.append(
                GearRecord(
                    piece_id=f"{troop}-{slot}", name=f"{troop} {slot}",
                    troop_type=troop, slot=slot, rarity="mythic",
                    enhancement_level=40, power=60_000,
                    stats=GearStats(
                        conquest={"Hero Attack": 300, "Hero Health": 1500},
                        expedition={f"{prefix[troop]} {stat}": 32.0},
                    ),
                )
            )
    return out


@pytest.fixture(scope="module")
def bundle() -> dict:
    return run_optimize_bundle(_heroes(), gear=_gear(), config_root=_ROOT)


def _check(contribution: dict) -> None:
    assert contribution["estimated"] is True
    assert set(contribution["power"]) == _SHARE_KEYS
    for block in [contribution["power"]] + list(contribution["stats"].values()):
        assert block["hero"] >= 0
        assert block["skills"] >= 0
        assert block["gear"] >= 0
        assert block["total"] == pytest.approx(
            block["hero"] + block["skills"] + block["gear"]
        )


def test_every_optimal_section_reports_contributions(bundle: dict) -> None:
    seen = 0
    for section in ("sword", "bear"):
        for row in (bundle[section].get("modes") or {}).values():
            assert row["stat_family"] == "expedition"
            _check(row["formation_totals"])
            for contrib in (row["contributions"] or {}).values():
                assert contrib["family"] == "expedition"
                _check(contrib)
            seen += 1
    for row in (bundle["arena"]["attack"], bundle["arena"]["defense"], bundle["conquest"]):
        if row.get("status") != "Optimal":
            continue
        assert row["stat_family"] == "conquest"
        _check(row["formation_totals"])
        for contrib in (row["contributions"] or {}).values():
            assert contrib["family"] == "conquest"
            _check(contrib)
        seen += 1
    assert seen >= 3, "expected at least three optimal sections to check"


def test_formation_totals_equal_sum_of_hero_contributions(bundle: dict) -> None:
    for row in (bundle["arena"]["attack"], bundle["conquest"]):
        if row.get("status") != "Optimal":
            continue
        totals = row["formation_totals"]
        contribs = list((row["contributions"] or {}).values())
        assert totals["power"]["total"] == pytest.approx(
            sum(c["power"]["total"] for c in contribs)
        )
        for label, share in totals["stats"].items():
            assert share["total"] == pytest.approx(
                sum((c["stats"].get(label) or {}).get("total", 0.0) for c in contribs)
            )


def test_no_scorer_still_uses_the_gear_bonus_heuristic() -> None:
    """Success criterion 4: naked power + heuristic gear bonus is gone."""
    optimize_dir = _ROOT / "ks" / "heroes" / "optimize"
    offenders = [
        path.name
        for path in sorted(optimize_dir.glob("*.py"))
        if "gear_bonus" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"heuristic gear bonus still referenced in {offenders}"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_heroes_optimize_contributions_wiring.py -v`
Expected: PASS

- [ ] **Step 3: Full suite**

Run: `uv run pytest -q`
Expected: PASS except the known pre-existing `test_best_sets_picks_highest_score_per_slot`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_heroes_optimize_contributions_wiring.py
git commit -m "test(heroes): assert every optimiser reads stat contributions"
```

---

## Success criteria check

| Design criterion | Task |
|------------------|------|
| 1. Board shows formation-level hero/skills/gear totals for the correct family | 7 (payload), 8 (`renderContributionStrip`) |
| 2. Hero sheet shows the same split per hero | 8 (`renderContributionTable`) |
| 3. Arena/Conquest/Swordland/Bear/Gear-XP derive strength from contributions | 3, 4, 5, 6 |
| 4. No scorer remains on naked power + heuristic gear bonus | 3 (deletes `gear_bonus_by_troop`), 4 (deletes `_provisional_gear_bonus`), 9 (guard test) |
| Arena-survival spec: same-rarity power sanitize | 5 Part A |
