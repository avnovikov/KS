"""Run sword/bear/arena/conquest optimize bundles for the UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.arena import load_arena_roles, optimize_arena
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.combat_formation import load_combat_roles
from ks.heroes.optimize.conquest import optimize_conquest
from ks.heroes.optimize.events import load_event_profile
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.scenarios import load_scenarios
from ks.heroes.optimize.troop_stats import load_troop_stats
from ks.heroes.optimize.troops import load_troops_config

REPO_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)

_DOMAIN_ERRORS = (ValueError, OSError, FileNotFoundError, yaml.YAMLError, KeyError)


def _event_bundle(
    label: str,
    heroes: list[HeroRecord],
    catalog: dict[str, Any],
    *,
    troops_path: Path,
    event_path: Path,
    scenarios_path: Path,
    troop_stats_path: Path,
    gear: list[GearRecord] | None,
    gear_profile: str,
) -> dict[str, Any]:
    troops = load_troops_config(troops_path)
    scenarios = load_scenarios(scenarios_path)
    event = load_event_profile(event_path)
    troop_stats = load_troop_stats(troop_stats_path)
    raw_troops = yaml.safe_load(troops_path.read_text(encoding="utf-8")) or {}
    truegold = int(raw_troops.get("truegold", troop_stats.default_truegold))
    modes: dict[str, Any] = {}
    mode_errors: dict[str, str] = {}
    for mode in scenarios:
        try:
            result = recommend(
                heroes,
                catalog,
                troops,
                scenarios,
                force_mode=mode,
                event=event,
                troop_stats=troop_stats,
                truegold=truegold,
                gear=gear,
                gear_profile=gear_profile,
            )
            modes[mode] = result.to_dict()
        except ValueError as exc:
            mode_errors[mode] = str(exc)
    if not modes and mode_errors:
        raise ValueError(
            "; ".join(f"{m}: {err}" for m, err in mode_errors.items())
        )
    out: dict[str, Any] = {
        "label": label,
        "event": event.name,
        "status": "ok",
        "modes": modes,
    }
    if mode_errors:
        out["mode_errors"] = mode_errors
    return out


def _section_error(label: str, message: str) -> dict[str, Any]:
    return {"label": label, "modes": {}, "status": "Error", "error": message}


def run_optimize_bundle(
    heroes: list[HeroRecord],
    *,
    gear: list[GearRecord] | None = None,
    config_root: Path | None = None,
    gear_profile_events: str = "early_game_growth",
    gear_profile_arena: str = "early_game_combat",
) -> dict[str, Any]:
    """Compute sword + bear mode tables, arena attack/defense, and conquest."""
    root = (config_root or REPO_ROOT).expanduser().resolve()
    catalog_path = root / "config" / "hero_catalog.yaml"
    troops_path = root / "config" / "troops.yaml"
    troop_stats_path = root / "config" / "troop_stats.yaml"
    roles_path = root / "config" / "arena_roles.yaml"
    conquest_roles_path = root / "config" / "conquest_roles.yaml"
    catalog = load_catalog(None, catalog_path)
    roles = load_arena_roles(roles_path, catalog=catalog)
    conquest_roles = load_combat_roles(conquest_roles_path, catalog=catalog)

    errors: dict[str, str] = {}
    warnings: list[str] = []
    out: dict[str, Any] = {"errors": errors, "warnings": warnings}

    try:
        out["sword"] = _event_bundle(
            "Swordland",
            heroes,
            catalog,
            troops_path=troops_path,
            event_path=root / "config" / "events" / "swordland.yaml",
            scenarios_path=root / "config" / "point_scenarios.yaml",
            troop_stats_path=troop_stats_path,
            gear=gear,
            gear_profile=gear_profile_events,
        )
    except _DOMAIN_ERRORS as exc:
        errors["sword"] = str(exc)
        out["sword"] = _section_error("Swordland", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("sword optimize failed")
        errors["sword"] = f"internal error: {exc}"
        out["sword"] = _section_error("Swordland", errors["sword"])

    try:
        out["bear"] = _event_bundle(
            "Bear Trap",
            heroes,
            catalog,
            troops_path=troops_path,
            event_path=root / "config" / "events" / "beartrap.yaml",
            scenarios_path=root / "config" / "point_scenarios_beartrap.yaml",
            troop_stats_path=troop_stats_path,
            gear=gear,
            gear_profile=gear_profile_events,
        )
    except _DOMAIN_ERRORS as exc:
        errors["bear"] = str(exc)
        out["bear"] = _section_error("Bear Trap", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("bear optimize failed")
        errors["bear"] = f"internal error: {exc}"
        out["bear"] = _section_error("Bear Trap", errors["bear"])

    arena: dict[str, Any] = {}
    for side in ("attack", "defense"):
        try:
            result = optimize_arena(
                side,
                heroes,
                catalog,
                roles,
                gear=gear,
                gear_profile=gear_profile_arena,
            )
            payload = result.to_dict()
            warn = (result.reasons or {}).get("_explain_warning")
            if warn:
                warnings.append(f"arena_{side}: {warn}")
            arena[side] = payload
        except _DOMAIN_ERRORS as exc:
            errors[f"arena_{side}"] = str(exc)
            arena[side] = {
                "side": side,
                "status": "Error",
                "formation": {},
                "heroes": [],
                "score": None,
                "reasons": {},
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("arena %s optimize failed", side)
            errors[f"arena_{side}"] = f"internal error: {exc}"
            arena[side] = {
                "side": side,
                "status": "Error",
                "formation": {},
                "heroes": [],
                "score": None,
                "reasons": {},
                "error": errors[f"arena_{side}"],
            }
    out["arena"] = arena

    try:
        conquest_result = optimize_conquest(
            heroes,
            catalog,
            conquest_roles,
            gear=gear,
            gear_profile=gear_profile_arena,
        )
        out["conquest"] = conquest_result.to_dict()
        if conquest_result.status != "Optimal":
            errors["conquest"] = f"status={conquest_result.status}"
    except _DOMAIN_ERRORS as exc:
        errors["conquest"] = str(exc)
        out["conquest"] = {
            "mode": "conquest",
            "status": "Error",
            "formation": {},
            "heroes": [],
            "score": None,
            "reasons": {},
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("conquest optimize failed")
        errors["conquest"] = f"internal error: {exc}"
        out["conquest"] = {
            "mode": "conquest",
            "status": "Error",
            "formation": {},
            "heroes": [],
            "score": None,
            "reasons": {},
            "error": errors["conquest"],
        }
    return out


def attach_gear_icon_urls(
    bundle: dict[str, Any],
    icon_by_piece_id: dict[str, str | None],
) -> None:
    """Mutate gear_assignment rows in-place with icon_url when known."""

    def _patch_assignment(assignment: dict[str, list[dict[str, Any]]] | None) -> None:
        if not assignment:
            return
        for pieces in assignment.values():
            for piece in pieces:
                pid = piece.get("piece_id")
                if pid and pid in icon_by_piece_id:
                    piece["icon_url"] = icon_by_piece_id[pid]

    for section in ("sword", "bear"):
        modes = (bundle.get(section) or {}).get("modes") or {}
        for row in modes.values():
            _patch_assignment(row.get("gear_assignment"))
    arena = bundle.get("arena") or {}
    for side_row in arena.values():
        if isinstance(side_row, dict):
            _patch_assignment(side_row.get("gear_assignment"))
    conquest = bundle.get("conquest")
    if isinstance(conquest, dict):
        _patch_assignment(conquest.get("gear_assignment"))
