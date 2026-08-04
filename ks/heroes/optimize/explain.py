"""Structured why-cards and leave-one-out marginals for optimize results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import hero_strength, normalize_troop
from ks.heroes.optimize.troop_stats import TroopStatsTable
from ks.heroes.optimize.types import (
    CatalogEntry,
    EventProfile,
    ModeSolution,
    Scenario,
    TroopsConfig,
)

_T = TypeVar("_T")


@dataclass(frozen=True)
class LeaveOneOutPoints:
    baseline_points: float
    points_without: float | None
    marginal_points: float | None
    critical: bool
    alternate_lineup: tuple[str, ...]
    status: str
    inconclusive: bool = False

    def __post_init__(self) -> None:
        if self.critical:
            assert self.points_without is None and self.marginal_points is None, (
                "critical LOO must null out points"
            )
        elif not self.inconclusive:
            assert self.points_without is not None and self.marginal_points is not None, (
                "non-critical LOO must include point deltas"
            )

    def to_dict(self) -> dict[str, Any]:
        lineup = list(self.alternate_lineup)
        return {
            "baseline_points": self.baseline_points,
            "points_without": self.points_without,
            "marginal_points": self.marginal_points,
            "critical": self.critical,
            "inconclusive": self.inconclusive,
            "alternate_lineup": lineup,
            # Compat alias used by older UI copy.
            "replacement_heroes": lineup,
            "status": self.status,
        }


@dataclass(frozen=True)
class LeaveOneOutScore:
    baseline_score: float
    score_without: float | None
    marginal_score: float | None
    critical: bool
    alternate_lineup: tuple[str, ...]
    replacement_formation: dict[str, str]
    status: str
    inconclusive: bool = False

    def __post_init__(self) -> None:
        if self.critical:
            assert self.score_without is None and self.marginal_score is None, (
                "critical LOO must null out scores"
            )
        elif not self.inconclusive:
            assert self.score_without is not None and self.marginal_score is not None, (
                "non-critical LOO must include score deltas"
            )

    def to_dict(self) -> dict[str, Any]:
        lineup = list(self.alternate_lineup)
        return {
            "baseline_score": self.baseline_score,
            "score_without": self.score_without,
            "marginal_score": self.marginal_score,
            "critical": self.critical,
            "inconclusive": self.inconclusive,
            "alternate_lineup": lineup,
            "replacement_heroes": lineup,
            "replacement_formation": dict(self.replacement_formation),
            "status": self.status,
        }


@dataclass(frozen=True)
class HeroExplain:
    role: str
    fits_because: tuple[str, ...]
    leave_one_out: LeaveOneOutPoints | LeaveOneOutScore
    slot: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "role": self.role,
            "fits_because": list(self.fits_because),
            "leave_one_out": self.leave_one_out.to_dict(),
        }
        if self.slot is not None:
            out["slot"] = self.slot
        if self.summary is not None:
            out["summary"] = self.summary
        return out


def _tier_for_mode(entry: CatalogEntry, mode: str) -> str | None:
    if mode == "garrison":
        return entry.garrison_tier
    if mode == "rally_lead":
        return entry.rally_tier
    if mode == "joiner":
        return entry.joiner_tier
    return None


def _role_label(entry: CatalogEntry | None, mode: str, scenario: Scenario) -> str:
    if entry is None:
        return "owned"
    widget = (entry.widget_type or "none").lower()
    req = (scenario.require_widget or "").lower()
    if req and widget == req:
        return f"{req}_widget"
    if mode == "joiner" and any(e.first_expedition for e in entry.effects):
        return "joiner_first_skill"
    if widget == "attack":
        return "attack_widget"
    if widget == "defense":
        return "defense_widget"
    troop = normalize_troop(entry.troop) or "flex"
    return f"{troop}_support"


def fits_because_event(
    name: str,
    catalog: dict[str, CatalogEntry],
    mode: str,
    scenario: Scenario,
    *,
    strength: float | None = None,
) -> list[str]:
    entry = catalog.get(name)
    bits: list[str] = []
    if entry is None:
        return ["Owned but missing from catalog"]
    widget = entry.widget_type or "none"
    req = scenario.require_widget
    if req and widget == req:
        bits.append(f"Satisfies required {req} widget for {mode}")
    elif req and widget != req:
        bits.append(f"Widget={widget} (requirement is {req})")
    else:
        bits.append(f"Widget={widget}")
    troop = normalize_troop(entry.troop)
    if troop:
        bits.append(f"Covers {troop} slot (one-per-troop formation)")
    tier = _tier_for_mode(entry, mode)
    if tier:
        bits.append(f"{mode} tier={tier}")
    first_skills = [e.kind for e in entry.effects if e.first_expedition]
    if mode == "joiner" and first_skills:
        bits.append(
            "First-expedition skill helps joiner scoring: " + ", ".join(first_skills)
        )
    if strength is not None:
        bits.append(f"Mode strength score={strength:.1f}")
    return bits


def _leave_one_out_map(
    names: list[str],
    heroes: list[HeroRecord],
    *,
    resolve_alt: Callable[[list[HeroRecord]], Any],
    on_optimal: Callable[[str, Any], _T],
    on_infeasible: Callable[[str, Any], _T],
    on_other: Callable[[str, Any], _T],
) -> dict[str, _T]:
    """Re-solve without each name; dispatch by alternate status."""
    out: dict[str, _T] = {}
    for name in names:
        reduced = [h for h in heroes if h.name != name]
        alt = resolve_alt(reduced)
        if alt.status == "Optimal":
            out[name] = on_optimal(name, alt)
        elif alt.status == "Infeasible":
            out[name] = on_infeasible(name, alt)
        else:
            out[name] = on_other(name, alt)
    return out


def leave_one_out_mode(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    troops: TroopsConfig,
    scenario: Scenario,
    baseline: ModeSolution,
    *,
    event: EventProfile | None = None,
    troop_stats: TroopStatsTable | None = None,
    truegold: int = 0,
    gear_bonus_by_troop: dict[str, float] | None = None,
) -> dict[str, LeaveOneOutPoints]:
    """Re-solve mode without each selected hero; report point drop."""
    from ks.heroes.optimize.model import solve_mode

    baseline_pts = float(baseline.expected_personal_points)

    def resolve_alt(reduced: list[HeroRecord]) -> Any:
        return solve_mode(
            reduced,
            catalog,
            troops,
            scenario,
            event=event,
            troop_stats=troop_stats,
            truegold=truegold,
            gear_bonus_by_troop=gear_bonus_by_troop,
        )

    def on_optimal(_name: str, alt: Any) -> LeaveOneOutPoints:
        without = float(alt.expected_personal_points)
        return LeaveOneOutPoints(
            baseline_points=baseline_pts,
            points_without=without,
            marginal_points=baseline_pts - without,
            critical=False,
            alternate_lineup=tuple(alt.hero_names),
            status="Optimal",
        )

    def on_infeasible(_name: str, alt: Any) -> LeaveOneOutPoints:
        return LeaveOneOutPoints(
            baseline_points=baseline_pts,
            points_without=None,
            marginal_points=None,
            critical=True,
            alternate_lineup=(),
            status=alt.status,
        )

    def on_other(_name: str, alt: Any) -> LeaveOneOutPoints:
        return LeaveOneOutPoints(
            baseline_points=baseline_pts,
            points_without=None,
            marginal_points=None,
            critical=False,
            alternate_lineup=(),
            status=alt.status,
            inconclusive=True,
        )

    return _leave_one_out_map(
        list(baseline.hero_names),
        heroes,
        resolve_alt=resolve_alt,
        on_optimal=on_optimal,
        on_infeasible=on_infeasible,
        on_other=on_other,
    )


def explain_selected_heroes(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    troops: TroopsConfig,
    scenario: Scenario,
    baseline: ModeSolution,
    *,
    event: EventProfile | None = None,
    troop_stats: TroopStatsTable | None = None,
    truegold: int = 0,
    gear_bonus_by_troop: dict[str, float] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Build hero rows with reason + explain (B) and leave-one-out (C)."""
    loo = leave_one_out_mode(
        heroes,
        catalog,
        troops,
        scenario,
        baseline,
        event=event,
        troop_stats=troop_stats,
        truegold=truegold,
        gear_bonus_by_troop=gear_bonus_by_troop,
    )
    hero_by_name = {h.name: h for h in heroes}
    rows: list[dict[str, Any]] = []
    for name in baseline.hero_names:
        entry = catalog.get(name)
        hero = hero_by_name.get(name)
        strength = None
        if entry is not None and hero is not None:
            strength = hero_strength(
                hero,
                entry,
                scenario.mode,
                event=event,
                effective_power=hero.power,
                gear_bonus=float(
                    (gear_bonus_by_troop or {}).get(
                        normalize_troop(entry.troop) or "", 0.0
                    )
                ),
            )
        role = _role_label(entry, scenario.mode, scenario)
        fits = tuple(
            fits_because_event(
                name, catalog, scenario.mode, scenario, strength=strength
            )
        )
        explain = HeroExplain(
            role=role,
            fits_because=fits,
            leave_one_out=loo[name],
        )
        summary_bits = [f"role={role}"]
        if entry and entry.troop:
            summary_bits.append(f"troop={entry.troop}")
        if entry and entry.widget_type:
            summary_bits.append(f"widget={entry.widget_type}")
        rows.append(
            {
                "name": name,
                "reason": ", ".join(summary_bits),
                "explain": explain.to_dict(),
            }
        )
    return tuple(rows)


def _arena_placement_bits(
    slot: str,
    family: str,
    role: str,
    troop: str,
    base_score: float,
    tags: list[str],
) -> list[str]:
    bits = [
        f"Placed {slot} ({family}) as {role.replace('_', ' ')}",
        f"troop={troop}",
        f"arena base score={base_score:.1f}",
    ]
    if tags:
        bits.append("tags=" + "+".join(tags))
    return bits


def _arena_side_bias_bits(
    side: str, tags: list[str], family: str, slot: str, carry_slot: str
) -> list[str]:
    """Extra why-card bits from tag/slot synergy with attack vs. defense side."""
    bits: list[str] = []
    if side == "defense":
        if "tank" in tags and family == "front":
            bits.append("Defense bias: tanks preferred on front")
        if "heal" in tags:
            bits.append("Defense bias: heal valued for offline sustain")
        if "team_def" in tags:
            bits.append("Defense bias: team defense tag boosted")
    elif ("dps" in tags or "aoe" in tags) and slot == carry_slot:
        bits.append(f"Attack carry slot ({carry_slot}) favors DPS/AoE")
    return bits


def fits_because_arena(
    name: str,
    slot: str,
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    *,
    base_score: float,
    side: str,
) -> tuple[str, list[str]]:
    meta = (roles.get("heroes") or {}).get(name) or {}
    entry = catalog.get(name)
    role = str(meta.get("role") or meta.get("arena_role") or "flex")
    tags = [str(t) for t in (meta.get("tags") or meta.get("arena_tags") or [])]
    troop = normalize_troop(entry.troop if entry else None) or "unknown"
    family = "front" if slot.startswith("F") else "back"
    carry_slot = str(roles.get("slots", {}).get("carry_slot") or "B2")

    bits = _arena_placement_bits(slot, family, role, troop, base_score, tags)
    bits.extend(_arena_side_bias_bits(side, tags, family, slot, carry_slot))
    if entry and entry.rarity:
        bits.append(f"rarity={entry.rarity}")
    return role, bits


def leave_one_out_arena(
    side: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    baseline_formation: dict[str, str],
    baseline_score: float,
    *,
    gear: list[Any] | None = None,
    gear_profile: str = "early_game_combat",
) -> dict[str, LeaveOneOutScore]:
    """Re-solve arena without each selected hero; report score drop."""
    from ks.heroes.optimize.arena import optimize_arena

    def resolve_alt(reduced: list[HeroRecord]) -> Any:
        return optimize_arena(
            side,
            reduced,
            catalog,
            roles,
            gear=gear,
            gear_profile=gear_profile,
            with_explanations=False,
            with_survival=False,
        )

    def on_optimal(_name: str, alt: Any) -> LeaveOneOutScore:
        without = float(alt.score)
        return LeaveOneOutScore(
            baseline_score=baseline_score,
            score_without=without,
            marginal_score=baseline_score - without,
            critical=False,
            alternate_lineup=tuple(alt.heroes),
            replacement_formation=dict(alt.formation),
            status="Optimal",
        )

    def on_infeasible(_name: str, alt: Any) -> LeaveOneOutScore:
        return LeaveOneOutScore(
            baseline_score=baseline_score,
            score_without=None,
            marginal_score=None,
            critical=True,
            alternate_lineup=(),
            replacement_formation={},
            status=alt.status,
        )

    def on_other(_name: str, alt: Any) -> LeaveOneOutScore:
        return LeaveOneOutScore(
            baseline_score=baseline_score,
            score_without=None,
            marginal_score=None,
            critical=False,
            alternate_lineup=(),
            replacement_formation={},
            status=alt.status,
            inconclusive=True,
        )

    return _leave_one_out_map(
        list(baseline_formation.values()),
        heroes,
        resolve_alt=resolve_alt,
        on_optimal=on_optimal,
        on_infeasible=on_infeasible,
        on_other=on_other,
    )


def explain_arena_formation(
    side: str,
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    roles: dict[str, Any],
    formation: dict[str, str],
    base_scores: dict[str, float],
    baseline_score: float,
    *,
    gear: list[Any] | None = None,
    gear_profile: str = "early_game_combat",
) -> dict[str, dict[str, Any]]:
    loo = leave_one_out_arena(
        side,
        heroes,
        catalog,
        roles,
        formation,
        baseline_score,
        gear=gear,
        gear_profile=gear_profile,
    )
    out: dict[str, dict[str, Any]] = {}
    for slot, name in formation.items():
        role, fits = fits_because_arena(
            name,
            slot,
            catalog,
            roles,
            base_score=float(base_scores.get(name, 0.0)),
            side=side,
        )
        explain = HeroExplain(
            role=role,
            fits_because=tuple(fits),
            leave_one_out=loo[name],
            slot=slot,
            summary=f"slot={slot}, role={role}",
        )
        out[name] = explain.to_dict()
    return out
