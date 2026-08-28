"""Arena attack/defense optimizer: pick 5 heroes and 2F+3B placement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.combat_formation import (
    load_combat_roles,
    solve_combat_formation,
)
from ks.heroes.optimize.opponent_models import GEAR_FRONT_FIRST
from ks.heroes.optimize.survival_pipeline import attach_survival
from ks.heroes.optimize.types import CatalogEntry

# Re-export for older imports that reference load_arena_roles directly.
load_arena_roles = load_combat_roles

# Front claims gear first so infantry tanks are not starved (survival model).
_ATTACK_GEAR_ORDER = GEAR_FRONT_FIRST
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
    stat_family: str = "conquest"
    contributions: dict[str, dict[str, Any]] | None = None
    formation_totals: dict[str, Any] | None = None

    @classmethod
    def from_combat(cls, result: Any) -> ArenaResult:
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
            stat_family=result.stat_family,
            contributions=result.contributions,
            formation_totals=result.formation_totals,
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
            "stat_family": self.stat_family,
            "contributions": self.contributions,
            "formation_totals": self.formation_totals,
        }
        if self.explanations is not None:
            out["explanations"] = self.explanations
        survival = (self.explanations or {}).get("survival")
        if survival is not None:
            out["survival"] = survival
        return out


def _attach_arena_survival(
    result: Any,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    side: str,
    gear: list[GearRecord] | None,
    gear_profile: str,
    gear_order: tuple[str, ...],
    with_survival: bool,
    governor: GovernorTroopBonuses | None = None,
) -> Any:
    if not with_survival:
        return result
    from ks.heroes.optimize.combat_formation import hero_base_score

    def _base(hero, entry, roles, *, effective_power, contribution):
        return hero_base_score(
            hero,
            entry,
            roles,
            effective_power=effective_power,
            contribution=contribution,
            side=side,
            governor=governor,
        )

    return attach_survival(
        result,
        heroes,
        catalog,
        roles,
        gear=gear,
        gear_profile=gear_profile,
        side=side,
        base_score_fn=_base,
        gear_order=gear_order,
        heuristic_mode="arena",
    )


def optimize_arena_attack(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
    with_survival: bool = True,
    governor: GovernorTroopBonuses | None = None,
) -> ArenaResult:
    combat = solve_combat_formation(
        "arena",
        heroes,
        catalog,
        roles,
        side="attack",
        gear=gear,
        gear_profile=gear_profile,
        gear_slot_order=_ATTACK_GEAR_ORDER,
        with_explanations=with_explanations,
        governor=governor,
    )
    combat = _attach_arena_survival(
        combat,
        heroes,
        catalog,
        roles,
        side="attack",
        gear=gear,
        gear_profile=gear_profile,
        gear_order=_ATTACK_GEAR_ORDER,
        with_survival=with_survival,
        governor=governor,
    )
    return ArenaResult.from_combat(combat)


def optimize_arena_defense(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
    with_survival: bool = True,
    governor: GovernorTroopBonuses | None = None,
) -> ArenaResult:
    """Offline defense: prefer tanks + heal; fronts claim gear first."""
    combat = solve_combat_formation(
        "arena",
        heroes,
        catalog,
        roles,
        side="defense",
        gear=gear,
        gear_profile=gear_profile,
        gear_slot_order=_DEFENSE_GEAR_ORDER,
        with_explanations=with_explanations,
        governor=governor,
    )
    combat = _attach_arena_survival(
        combat,
        heroes,
        catalog,
        roles,
        side="defense",
        gear=gear,
        gear_profile=gear_profile,
        gear_order=_DEFENSE_GEAR_ORDER,
        with_survival=with_survival,
        governor=governor,
    )
    return ArenaResult.from_combat(combat)


def optimize_arena(
    side: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    gear: list[GearRecord] | None = None,
    gear_profile: str = "early_game_combat",
    with_explanations: bool = True,
    with_survival: bool = True,
    governor: GovernorTroopBonuses | None = None,
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
        with_survival=with_survival,
        governor=governor,
    )
