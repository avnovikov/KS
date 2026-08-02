"""Structured why-cards and leave-one-out marginals for optimize results."""

from __future__ import annotations

from typing import Any

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
        bits.append("First-expedition skill helps joiner scoring: " + ", ".join(first_skills))
    if strength is not None:
        bits.append(f"Mode strength score={strength:.1f}")
    return bits


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
) -> dict[str, dict[str, Any]]:
    """Re-solve mode without each selected hero; report point drop."""
    from ks.heroes.optimize.model import solve_mode

    out: dict[str, dict[str, Any]] = {}
    baseline_pts = float(baseline.expected_personal_points)
    for name in baseline.hero_names:
        reduced = [h for h in heroes if h.name != name]
        alt = solve_mode(
            reduced,
            catalog,
            troops,
            scenario,
            event=event,
            troop_stats=troop_stats,
            truegold=truegold,
            gear_bonus_by_troop=gear_bonus_by_troop,
        )
        if alt.status != "Optimal":
            out[name] = {
                "baseline_points": baseline_pts,
                "points_without": None,
                "marginal_points": None,
                "critical": True,
                "replacement_heroes": [],
                "status": alt.status,
            }
        else:
            without = float(alt.expected_personal_points)
            out[name] = {
                "baseline_points": baseline_pts,
                "points_without": without,
                "marginal_points": baseline_pts - without,
                "critical": False,
                "replacement_heroes": list(alt.hero_names),
                "status": "Optimal",
            }
    return out


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
        fits = fits_because_event(
            name, catalog, scenario.mode, scenario, strength=strength
        )
        loo_row = loo[name]
        if loo_row.get("critical"):
            fits = [*fits, "Critical: no feasible lineup if removed"]
        elif loo_row.get("marginal_points") is not None:
            fits = [
                *fits,
                f"Leave-one-out: −{loo_row['marginal_points']:.0f} pts if removed",
            ]
        summary_bits = [f"role={role}"]
        if entry and entry.troop:
            summary_bits.append(f"troop={entry.troop}")
        if entry and entry.widget_type:
            summary_bits.append(f"widget={entry.widget_type}")
        rows.append(
            {
                "name": name,
                "reason": ", ".join(summary_bits),
                "explain": {
                    "role": role,
                    "fits_because": fits,
                    "leave_one_out": loo_row,
                },
            }
        )
    return tuple(rows)


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
    bits = [
        f"Placed {slot} ({family}) as {role.replace('_', ' ')}",
        f"troop={troop}",
        f"arena base score={base_score:.1f}",
    ]
    if tags:
        bits.append("tags=" + "+".join(tags))
    if side == "defense":
        if "tank" in tags and family == "front":
            bits.append("Defense bias: tanks preferred on front")
        if "heal" in tags:
            bits.append("Defense bias: heal valued for offline sustain")
        if "team_def" in tags:
            bits.append("Defense bias: team defense tag boosted")
    elif "dps" in tags or "aoe" in tags:
        if slot == "B2":
            bits.append("Attack carry slot (B2) favors DPS/AoE")
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
) -> dict[str, dict[str, Any]]:
    """Re-solve arena without each selected hero; report score drop."""
    from ks.heroes.optimize.arena import optimize_arena

    out: dict[str, dict[str, Any]] = {}
    selected = list(baseline_formation.values())
    for name in selected:
        reduced = [h for h in heroes if h.name != name]
        alt = optimize_arena(
            side,
            reduced,
            catalog,
            roles,
            gear=gear,
            gear_profile=gear_profile,
            with_explanations=False,
        )
        if alt.status != "Optimal":
            out[name] = {
                "baseline_score": baseline_score,
                "score_without": None,
                "marginal_score": None,
                "critical": True,
                "replacement_formation": {},
                "status": alt.status,
            }
        else:
            without = float(alt.score)
            out[name] = {
                "baseline_score": baseline_score,
                "score_without": without,
                "marginal_score": baseline_score - without,
                "critical": False,
                "replacement_formation": dict(alt.formation),
                "replacement_heroes": list(alt.heroes),
                "status": "Optimal",
            }
    return out


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
        loo_row = loo[name]
        if loo_row.get("critical"):
            fits = [*fits, "Critical: no feasible 5 if removed"]
        elif loo_row.get("marginal_score") is not None:
            fits = [
                *fits,
                f"Leave-one-out: −{loo_row['marginal_score']:.1f} score if removed",
            ]
        out[name] = {
            "slot": slot,
            "role": role,
            "fits_because": fits,
            "leave_one_out": loo_row,
            "summary": f"slot={slot}, role={role}",
        }
    return out
