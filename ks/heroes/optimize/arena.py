"""Arena attack/defense optimizer: pick 5 heroes and 2F+3B placement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.combat_formation import (
    ALL_SLOTS,
    BACK,
    FRONT,
    CombatFormationResult,
    load_combat_roles,
    solve_combat_formation,
)
from ks.heroes.optimize.types import CatalogEntry

# Re-export for older imports that reference load_arena_roles directly.
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
        assert result.side is not None, "CombatFormationResult.side must be set for Arena"
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
        # Keep exact previous keys (no "mode") for CLI/UI consumers.
        out: dict[str, Any] = {
            "side": self.side,
            "formation": dict(self.formation),
            "heroes": list(self.heroes),
            "score": self.score,
            "gear_assignment": self.gear_assignment,
            "reasons": dict(self.reasons),
            "status": self.status,
        }
        if self.explanations is not None:
            out["explanations"] = self.explanations
        return out


def optimize_arena_attack(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
) -> ArenaResult:
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


def optimize_arena_defense(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
) -> ArenaResult:
    """Offline defense: prefer tanks + heal; fronts claim gear first."""
    return ArenaResult.from_combat(
        solve_combat_formation(
            "arena",
            heroes,
            catalog,
            roles,
            side="defense",
            gear=gear,
            gear_profile=gear_profile,
            gear_slot_order=_DEFENSE_GEAR_ORDER,
            with_explanations=with_explanations,
        )
    )


def optimize_arena(
    side: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
) -> ArenaResult:
    solvers: dict[str, Callable[..., ArenaResult]] = {
        "attack": optimize_arena_attack,
        "defense": optimize_arena_defense,
    }
    if side not in solvers:
        raise ValueError(
            f"unsupported arena side {side!r}; have {sorted(solvers)}"
        )
    return solvers[side](
        heroes,
        catalog,
        roles,
        gear=gear,
        gear_profile=gear_profile,
        with_explanations=with_explanations,
    )
