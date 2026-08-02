# Conquest Formation Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a shared 5-hero 2F+3B combat ILP from Arena and add a Conquest optimiser (math + CLI only).

**Architecture:** New `combat_formation.py` owns slots, result type, role loading, scoring helpers, and `solve_combat_formation`. `arena.py` and `conquest.py` are thin mode profiles. CLI gains `ks-heroes conquest`.

**Tech Stack:** Python 3.13, PuLP (CBC), pytest, existing `HeroRecord` / `CatalogEntry` / `gear_assign`.

## Global Constraints

- Work only in `.worktrees/feature-conquest-formation-optimizer` on branch `feature/conquest-formation-optimizer`
- Conquest formation is **5 heroes**, slots `F1,F2,B1,B2,B3` (same as Arena)
- No UI / `/optimize` changes
- Keep public Arena API stable (`optimize_arena_attack`, `optimize_arena_defense`, `optimize_arena`, `load_arena_roles`, `ArenaResult`)
- Gear profile default: `early_game_combat`
- Ultimate bonus: `1.0 + 0.04 * min(level, 10)` on Conquest skill slot 0 when level is present
- Follow TDD: failing test → implement → pass → commit per task

## File structure

| Path | Responsibility |
|------|----------------|
| `ks/heroes/optimize/combat_formation.py` | Shared slots, `CombatFormationResult`, load roles, ILP |
| `ks/heroes/optimize/arena.py` | Arena attack/defense wrappers + `ArenaResult` alias |
| `ks/heroes/optimize/conquest.py` | `optimize_conquest`, ultimate bonus, Conquest gear order |
| `config/conquest_roles.yaml` | Conquest placement multipliers |
| `ks/heroes/cli.py` | `conquest` subcommand |
| `tests/test_heroes_optimize_combat_formation.py` | Shared extract smoke |
| `tests/test_heroes_optimize_conquest.py` | Conquest behaviour |
| `docs/superpowers/specs/2026-08-02-conquest-formation-optimizer-design.md` | Spec (already written) |

---

### Task 1: Extract shared `combat_formation` module (Arena stays green)

**Files:**
- Create: `ks/heroes/optimize/combat_formation.py`
- Modify: `ks/heroes/optimize/arena.py` (re-export / thin wrappers)
- Test: `tests/test_heroes_optimize_combat_formation.py`
- Keep green: `tests/test_heroes_optimize_arena.py`, `tests/test_heroes_optimize_arena_defense.py`

**Interfaces:**
- Produces:
  - `FRONT: tuple[str, ...]`, `BACK`, `ALL_SLOTS`
  - `CombatFormationResult` dataclass with `to_dict()` including `mode` and optional `side`
  - `load_combat_roles(path: Path | str, catalog: dict[str, CatalogEntry] | None = None) -> dict[str, Any]`
  - `solve_combat_formation(mode: str, heroes, catalog, roles, *, side: str | None, gear, gear_profile, gear_slot_order, base_score_fn, placement_mult_fn, with_explanations, explain_fn) -> CombatFormationResult`
- Consumes: existing `assign_exclusive_sets`, `piece_score`, `normalize_troop`, `star_progress_factor`, pulp

- [ ] **Step 1: Write the failing import smoke test**

```python
# tests/test_heroes_optimize_combat_formation.py
from ks.heroes.optimize.combat_formation import ALL_SLOTS, FRONT, BACK


def test_slots_match_arena_shape() -> None:
    assert FRONT == ("F1", "F2")
    assert BACK == ("B1", "B2", "B3")
    assert ALL_SLOTS == FRONT + BACK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/alexei/KS/.worktrees/feature-conquest-formation-optimizer && pytest tests/test_heroes_optimize_combat_formation.py::test_slots_match_arena_shape -v`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `combat_formation`

- [ ] **Step 3: Create `combat_formation.py` by moving shared pieces from `arena.py`**

Move into `combat_formation.py` (keep behaviour identical):

- Slot constants
- Rename result type to `CombatFormationResult` with fields:
  - `mode: str`
  - `side: str | None`
  - `formation`, `heroes`, `score`, `gear_assignment`, `reasons`, `status`, `explanations`
  - `to_dict()` includes `mode` and `side` when not None
- `load_combat_roles` (same body as `load_arena_roles`)
- `_meta_for`, `_hero_tags`, `_hero_base_score`, `_placement_table`, `_placement_mult`, `_provisional_gear_bonus`, `_reason`
- `_solve` renamed to `solve_combat_formation` with parameters:
  - `mode: str`
  - `side: str | None = None` (Arena passes `"attack"` / `"defense"`; used only by placement/score helpers that need side)
  - `base_score_fn` optional — if None, use `_hero_base_score` with `side or "attack"`
  - `placement_mult_fn` optional — if None, use `_placement_mult`
  - keep gear assignment + optional explain hook

Minimal `solve_combat_formation` signature:

```python
def solve_combat_formation(
    mode: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    side: str | None = None,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    gear_slot_order: tuple[str, ...],
    base_score_fn: Callable[..., float] | None = None,
    placement_mult_fn: Callable[..., float] | None = None,
    with_explanations: bool = True,
    explain_fn: Callable[..., dict[str, dict[str, Any]]] | None = None,
) -> CombatFormationResult:
    ...
```

When `with_explanations` and `explain_fn` is None and `mode == "arena"`, import and call existing `explain_arena_formation` (preserve Arena behaviour). When `mode == "conquest"`, skip explain unless a fn is passed (v1).

- [ ] **Step 4: Thin `arena.py` wrappers**

```python
"""Arena attack/defense optimizer: pick 5 heroes and 2F+3B placement."""

from ks.heroes.optimize.combat_formation import (
    ALL_SLOTS,
    BACK,
    FRONT,
    CombatFormationResult,
    load_combat_roles,
    solve_combat_formation,
)

# re-export for older imports
load_arena_roles = load_combat_roles

_ATTACK_GEAR_ORDER = ("B2", "F1", "F2", "B1", "B3")
_DEFENSE_GEAR_ORDER = ("F1", "F2", "B2", "B3", "B1")


@dataclass(frozen=True)
class ArenaResult:
    side: str
    formation: dict[str, str]
    heroes: tuple[str, ...]
    score: float
    gear_assignment: dict[str, list[dict[str, Any]]] | None
    reasons: dict[str, str]
    status: str = "Optimal"
    explanations: dict[str, dict[str, Any]] | None = None

    @classmethod
    def from_combat(cls, result: CombatFormationResult) -> ArenaResult:
        assert result.side is not None
        return cls(
            side=result.side,
            formation=dict(result.formation),
            heroes=result.heroes,
            score=result.score,
            gear_assignment=result.gear_assignment,
            reasons=dict(result.reasons),
            status=result.status,
            explanations=result.explanations,
        )

    def to_dict(self) -> dict[str, Any]:
        # keep exact previous keys (no required "mode") for CLI/UI consumers
        ...


def optimize_arena_attack(...) -> ArenaResult:
    return ArenaResult.from_combat(
        solve_combat_formation(
            "arena",
            heroes,
            catalog,
            roles,
            side="attack",
            gear=gear,
            gear_profile=gear_profile,
            gear_slot_order=_ATTACK_GEAR_ORDER,
            with_explanations=with_explanations,
        )
    )
# similarly for defense / optimize_arena dispatcher
```

- [ ] **Step 5: Run smoke + Arena suite**

Run:

```bash
cd /Users/alexei/KS/.worktrees/feature-conquest-formation-optimizer
pytest tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_arena_defense.py tests/test_heroes_optimize_explain.py -q
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add ks/heroes/optimize/combat_formation.py ks/heroes/optimize/arena.py tests/test_heroes_optimize_combat_formation.py
git commit -m "$(cat <<'EOF'
refactor(heroes): extract shared combat formation ILP from arena

EOF
)"
```

---

### Task 2: Conquest config + `optimize_conquest`

**Files:**
- Create: `config/conquest_roles.yaml`
- Create: `ks/heroes/optimize/conquest.py`
- Test: `tests/test_heroes_optimize_conquest.py`

**Interfaces:**
- Consumes: `solve_combat_formation`, `load_combat_roles`, `CombatFormationResult`
- Produces:
  - `CONQUEST_GEAR_ORDER = ("F1", "F2", "B2", "B1", "B3")`
  - `ultimate_level_multiplier(hero: HeroRecord) -> float`
  - `optimize_conquest(heroes, catalog, roles, *, gear=None, gear_profile="early_game_combat", with_explanations=False) -> CombatFormationResult`

- [ ] **Step 1: Write failing Conquest tests**

```python
# tests/test_heroes_optimize_conquest.py
from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.optimize.catalog import CatalogEntry
from ks.heroes.optimize.conquest import (
    optimize_conquest,
    ultimate_level_multiplier,
)
from ks.heroes.optimize.combat_formation import load_combat_roles


def _catalog() -> dict[str, CatalogEntry]:
    # same seven-hero catalog as test_heroes_optimize_arena.py
    ...


def _heroes() -> list[HeroRecord]:
    # same power/stars as arena attack test
    ...


def test_conquest_picks_five_with_two_front() -> None:
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=_catalog())
    result = optimize_conquest(_heroes(), _catalog(), roles)
    assert result.status == "Optimal"
    assert result.mode == "conquest"
    assert len(result.heroes) == 5
    assert set(result.formation) == {"F1", "F2", "B1", "B2", "B3"}


def test_ultimate_multiplier_scales_with_slot0_level() -> None:
    bare = HeroRecord(name="X", skills=())
    mid = HeroRecord(
        name="Y",
        skills=(SkillRecord(slot=0, name="Ult", level=5),),
    )
    assert ultimate_level_multiplier(bare) == 1.0
    assert ultimate_level_multiplier(mid) == 1.0 + 0.04 * 5


def test_higher_ultimate_preferred_when_otherwise_equal() -> None:
    # Two infantry tanks with identical power/stars/catalog value;
    # only skill levels differ — higher ultimate should win a front slot.
    catalog = {
        "Howard": CatalogEntry(
            name="Howard", troop="infantry", rarity="epic",
            arena_role="front_tank", arena_value=85, arena_tags=("tank",),
        ),
        "Helga": CatalogEntry(
            name="Helga", troop="infantry", rarity="legendary",
            arena_role="front_fighter", arena_value=85, arena_tags=("tank",),
        ),
        # fill 3 more backline heroes so solve is feasible...
    }
    heroes = [
        HeroRecord(name="Howard", stars=3, pellets=0, power=400000, skills=(
            SkillRecord(slot=0, name="U", level=10),
        )),
        HeroRecord(name="Helga", stars=3, pellets=0, power=400000, skills=(
            SkillRecord(slot=0, name="U", level=1),
        )),
        # + 3 others with mid power
    ]
    roles = load_combat_roles("config/conquest_roles.yaml", catalog=catalog)
    result = optimize_conquest(heroes, catalog, roles)
    front = {result.formation["F1"], result.formation["F2"]}
    assert "Howard" in front
```

Copy the full seven-hero fixtures from `tests/test_heroes_optimize_arena.py` for the first test; for the third test include at least five heroes total.

- [ ] **Step 2: Run tests — expect fail**

Run: `pytest tests/test_heroes_optimize_conquest.py -v`

Expected: FAIL importing `conquest` / missing config

- [ ] **Step 3: Add `config/conquest_roles.yaml`**

Start from `config/arena_roles.yaml` `placement:` block with Conquest front bias:

```yaml
# Conquest placement multipliers (5 heroes, 2F+3B).
# Hero roles/values from hero_catalog.yaml via load_combat_roles.
slots:
  front: [F1, F2]
  back: [B1, B2, B3]
  carry_slot: B2
placement:
  infantry_front: 1.30
  cavalry_front: 1.05
  archers_front: 0.50
  infantry_back: 0.85
  cavalry_back: 1.10
  archers_back: 1.15
  carry_slot_bonus: 1.10
  front_tank_bonus: 1.15
```

- [ ] **Step 4: Implement `conquest.py`**

```python
"""Conquest optimizer: 5 heroes, 2F+3B, Conquest-skill aware scoring."""

from __future__ import annotations

from typing import Any

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.combat_formation import (
    CombatFormationResult,
    _hero_base_score,
    _placement_mult,
    solve_combat_formation,
)
from ks.heroes.optimize.types import CatalogEntry

CONQUEST_GEAR_ORDER = ("F1", "F2", "B2", "B1", "B3")
_ULTIMATE_LEVEL_WEIGHT = 0.04


def ultimate_level_multiplier(hero: HeroRecord) -> float:
    level = None
    for skill in hero.skills:
        if skill.slot == 0 and skill.level is not None:
            level = int(skill.level)
            break
    if level is None:
        return 1.0
    if level < 0:
        raise ValueError(f"skill level must be >= 0; got {level} for {hero.name}")
    return 1.0 + _ULTIMATE_LEVEL_WEIGHT * min(level, 10)


def _conquest_base_score(
    hero: HeroRecord,
    entry: CatalogEntry | None,
    roles: dict[str, Any],
    *,
    effective_power: int | None,
    gear_bonus: float,
    side: str,
) -> float:
    base = _hero_base_score(
        hero,
        entry,
        roles,
        effective_power=effective_power,
        gear_bonus=gear_bonus,
        side="attack",  # no defense tags for Conquest
    )
    return base * ultimate_level_multiplier(hero)


def optimize_conquest(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = False,
) -> CombatFormationResult:
    return solve_combat_formation(
        "conquest",
        heroes,
        catalog,
        roles,
        side=None,
        gear=gear,
        gear_profile=gear_profile,
        gear_slot_order=CONQUEST_GEAR_ORDER,
        base_score_fn=_conquest_base_score,
        placement_mult_fn=lambda troop, slot, name, roles, *, side: _placement_mult(
            troop, slot, name, roles, side="attack"
        ),
        with_explanations=with_explanations,
        explain_fn=None,
    )
```

Note: if `_hero_base_score` / `_placement_mult` are private, either export public helpers from `combat_formation` (`hero_base_score`, `placement_mult`) or keep them module-public for conquest (prefer renaming to public without leading underscore when extracting).

- [ ] **Step 5: Run Conquest + Arena tests**

Run:

```bash
pytest tests/test_heroes_optimize_conquest.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_arena_defense.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config/conquest_roles.yaml ks/heroes/optimize/conquest.py tests/test_heroes_optimize_conquest.py
git commit -m "$(cat <<'EOF'
feat(heroes): add Conquest 5-hero formation optimizer

EOF
)"
```

---

### Task 3: CLI `ks-heroes conquest`

**Files:**
- Modify: `ks/heroes/cli.py` (parser + `_cmd_conquest` + dispatch)
- Test: extend `tests/test_heroes_optimize_conquest.py` or add `tests/test_heroes_cli_conquest.py` with argparse smoke if the repo already tests CLI; otherwise manual CLI run with a tiny JSON fixture written in the test tmp path.

**Interfaces:**
- Consumes: `load_combat_roles`, `optimize_conquest`, existing hero/gear load helpers used by `_cmd_arena`
- Produces: writes JSON via `CombatFormationResult.to_dict()`

- [ ] **Step 1: Mirror arena CLI wiring**

In `cli.py`, after the `arena` subparser block, add:

```python
    conquest = sub.add_parser(
        "conquest",
        help="Pick Conquest formation (5 heroes, 2F+3B).",
    )
    conquest.add_argument("--heroes", type=Path, required=True, ...)
    conquest.add_argument("--catalog", type=Path, default=ROOT / "config" / "hero_catalog.yaml", ...)
    conquest.add_argument("--pro-cache", type=Path, default=..., ...)
    conquest.add_argument(
        "--roles",
        type=Path,
        default=ROOT / "config" / "conquest_roles.yaml",
        help="Conquest placement weights YAML.",
    )
    conquest.add_argument("--gear", type=Path, default=None, ...)
    conquest.add_argument("--gear-profile", type=str, default="early_game_combat", ...)
    conquest.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts" / "heroes" / "conquest_result.json",
        ...
    )
```

Implement `_cmd_conquest` by copying `_cmd_arena` and replacing:

- `load_arena_roles` → `load_combat_roles`
- `optimize_arena(...)` → `optimize_conquest(...)`
- print header `conquest formation (2 front / 3 back):`
- no `--side`

Wire `if args.command == "conquest": return _cmd_conquest(args)`.

- [ ] **Step 2: Manual/CLI smoke with fixture**

Create a minimal heroes JSON in `/tmp` or use existing `artifacts` if present:

```bash
cd /Users/alexei/KS/.worktrees/feature-conquest-formation-optimizer
# If artifacts/heroes/heroes.json exists:
ks-heroes conquest --heroes artifacts/heroes/heroes.json --out /tmp/conquest_result.json
# else run pytest-only path: write fixture in a small test that invokes optimize_conquest end-to-end (already Task 2)
```

Expected: exit 0, JSON has `mode: conquest`, five formation slots.

- [ ] **Step 3: Run full related suite**

```bash
pytest tests/test_heroes_optimize_conquest.py tests/test_heroes_optimize_combat_formation.py tests/test_heroes_optimize_arena.py tests/test_heroes_optimize_arena_defense.py tests/test_heroes_optimize_explain.py -q
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ks/heroes/cli.py
git commit -m "$(cat <<'EOF'
feat(heroes): add ks-heroes conquest CLI

EOF
)"
```

---

### Task 4: Spec self-check note + README pointer (docs only)

**Files:**
- Modify: `config/hero_gear_optimizer/README.md` — one line that Conquest formation optimiser exists and values R+40/R+80 for combat profile
- Confirm: design spec already at `docs/superpowers/specs/2026-08-02-conquest-formation-optimizer-design.md`

- [ ] **Step 1: Add README cross-link**

Under the imbuement table note, add:

```markdown
Conquest/Arena formation math: `ks-heroes conquest` / `ks-heroes arena` (shared `combat_formation` ILP). For early combat, prefer `early_game_combat` and do not skip Conquest imbuements (R+40 / R+80).
```

- [ ] **Step 2: Commit**

```bash
git add config/hero_gear_optimizer/README.md docs/superpowers/specs/2026-08-02-conquest-formation-optimizer-design.md docs/superpowers/plans/2026-08-02-conquest-formation-optimizer.md
git commit -m "$(cat <<'EOF'
docs(heroes): Conquest formation optimizer spec and plan

EOF
)"
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Extract shared ILP | Task 1 |
| Arena API stable | Task 1 |
| `optimize_conquest` 5/2F+3B | Task 2 |
| Ultimate level bonus | Task 2 |
| `conquest_roles.yaml` + front gear order | Task 2 |
| CLI `ks-heroes conquest` | Task 3 |
| No UI | (all tasks — no UI files) |
| Sources & encoding limits documented | Spec file + Task 4 |

## Placeholder scan

None intentional — ultimate weight `0.04` is fixed in code; explainability for Conquest deferred explicitly via `with_explanations=False`.
