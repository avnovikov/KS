"""Run sword/bear/arena/conquest optimize bundles for the UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.arena import load_arena_roles, optimize_arena
from ks.heroes.optimize.catalog import load_catalog
from ks.heroes.optimize.combat_formation import load_combat_roles
from ks.heroes.optimize.conquest import optimize_conquest
from ks.heroes.optimize.events import load_event_profile
from ks.heroes.optimize.recommend import recommend
from ks.heroes.optimize.scenarios import load_scenarios
from ks.heroes.optimize.stat_contributions import family_for_event
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
    governor: GovernorTroopBonuses | None = None,
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
                governor=governor,
            )
            payload = result.to_dict()
            payload["contributions"] = {
                row["name"]: row["contributions"]
                for row in payload.get("heroes") or []
                if row.get("name") and row.get("contributions")
            } or None
            modes[mode] = payload
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
        "stat_family": family_for_event(event.name),
        "modes": modes,
    }
    if mode_errors:
        out["mode_errors"] = mode_errors
    return out


def _section_error(label: str, message: str, *, stat_family: str) -> dict[str, Any]:
    return {
        "label": label,
        "modes": {},
        "status": "Error",
        "error": message,
        "stat_family": stat_family,
    }


def _formation_error(message: str, **identity: str) -> dict[str, Any]:
    """The shape a failed 5-hero formation section returns.

    `identity` is `side="attack"` for an arena side and `mode="conquest"` for
    Conquest, matching which of the two keys CombatFormationResult.to_dict()
    emits for each — it omits `side` when the solver had none.
    """
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


def run_optimize_bundle(
    heroes: list[HeroRecord],
    *,
    gear: list[GearRecord] | None = None,
    config_root: Path | None = None,
    troops_path: Path | None = None,
    gear_profile_events: str = "early_game_growth",
    gear_profile_arena: str = "early_game_combat",
    governor: GovernorTroopBonuses | None = None,
) -> dict[str, Any]:
    """Compute sword + bear mode tables, arena attack/defense, and conquest.

    `troops_path` overrides where troop counts/truegold are read from (the
    UI-editable copy); it defaults to the repo-relative config/troops.yaml
    used by every caller before Task 2 wired in a store.

    Only the two event bundles consume it. `optimize_arena` and
    `optimize_conquest` score a 5-hero formation from the catalog, their
    roles YAML and gear alone — neither reads troop counts or truegold, so
    there is no fourth place for an edited troop count to leak past. That is
    a behavioural claim, not a comment: the sole read of a troops file under
    this function is `_event_bundle`'s, and
    test_no_section_reads_a_second_troops_file pins that the repo's
    config/troops.yaml is never opened once an override is supplied.
    """
    root = (config_root or REPO_ROOT).expanduser().resolve()
    catalog_path = root / "config" / "hero_catalog.yaml"
    resolved_troops_path = (
        Path(troops_path).expanduser().resolve()
        if troops_path is not None
        else root / "config" / "troops.yaml"
    )
    troop_stats_path = root / "config" / "troop_stats.yaml"
    roles_path = root / "config" / "arena_roles.yaml"
    conquest_roles_path = root / "config" / "conquest_roles.yaml"
    # The catalog is the one genuinely shared input — every section scores
    # against it — so a failure here is still fatal for the request.
    catalog = load_catalog(None, catalog_path)

    errors: dict[str, str] = {}
    warnings: list[str] = []
    out: dict[str, Any] = {"errors": errors, "warnings": warnings}

    def _load_roles(loader: Any, path: Path, keys: tuple[str, ...]) -> Any:
        """Load one roles YAML, charging any failure to its own sections.

        These two loads used to sit above `errors`, outside every try block,
        so a missing or malformed conquest_roles.yaml raised straight out of
        run_optimize_bundle and 500'd /api/optimize — taking Swordland, Bear
        Trap and Arena down with Conquest, which is exactly the partial
        failure the Conquest spec said must not happen. arena_roles.yaml had
        the identical exposure.
        """
        try:
            return loader(path, catalog=catalog)
        except _DOMAIN_ERRORS as exc:
            for key in keys:
                errors[key] = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s roles load failed", path.name)
            for key in keys:
                errors[key] = f"internal error: {exc}"
        return None

    roles = _load_roles(load_arena_roles, roles_path, ("arena_attack", "arena_defense"))
    conquest_roles = _load_roles(load_combat_roles, conquest_roles_path, ("conquest",))

    try:
        out["sword"] = _event_bundle(
            "Swordland",
            heroes,
            catalog,
            troops_path=resolved_troops_path,
            event_path=root / "config" / "events" / "swordland.yaml",
            scenarios_path=root / "config" / "point_scenarios.yaml",
            troop_stats_path=troop_stats_path,
            gear=gear,
            gear_profile=gear_profile_events,
            governor=governor,
        )
    except _DOMAIN_ERRORS as exc:
        errors["sword"] = str(exc)
        out["sword"] = _section_error("Swordland", str(exc), stat_family="expedition")
    except Exception as exc:  # noqa: BLE001
        logger.exception("sword optimize failed")
        errors["sword"] = f"internal error: {exc}"
        out["sword"] = _section_error("Swordland", errors["sword"], stat_family="expedition")

    try:
        out["bear"] = _event_bundle(
            "Bear Trap",
            heroes,
            catalog,
            troops_path=resolved_troops_path,
            event_path=root / "config" / "events" / "beartrap.yaml",
            scenarios_path=root / "config" / "point_scenarios_beartrap.yaml",
            troop_stats_path=troop_stats_path,
            gear=gear,
            gear_profile=gear_profile_events,
            governor=governor,
        )
    except _DOMAIN_ERRORS as exc:
        errors["bear"] = str(exc)
        out["bear"] = _section_error("Bear Trap", str(exc), stat_family="expedition")
    except Exception as exc:  # noqa: BLE001
        logger.exception("bear optimize failed")
        errors["bear"] = f"internal error: {exc}"
        out["bear"] = _section_error("Bear Trap", errors["bear"], stat_family="expedition")

    arena: dict[str, Any] = {}
    for side in ("attack", "defense"):
        if roles is None:
            # _load_roles already charged the failure to both arena keys.
            arena[side] = _formation_error(errors[f"arena_{side}"], side=side)
            continue
        try:
            result = optimize_arena(
                side,
                heroes,
                catalog,
                roles,
                gear=gear,
                gear_profile=gear_profile_arena,
                governor=governor,
            )
            payload = result.to_dict()
            warn = (result.reasons or {}).get("_explain_warning")
            if warn:
                warnings.append(f"arena_{side}: {warn}")
            arena[side] = payload
        except _DOMAIN_ERRORS as exc:
            errors[f"arena_{side}"] = str(exc)
            arena[side] = _formation_error(str(exc), side=side)
        except Exception as exc:  # noqa: BLE001
            logger.exception("arena %s optimize failed", side)
            errors[f"arena_{side}"] = f"internal error: {exc}"
            arena[side] = _formation_error(errors[f"arena_{side}"], side=side)
    out["arena"] = arena

    if conquest_roles is None:
        # _load_roles already charged the failure to errors["conquest"].
        # Deliberately not an early `return out`: this is the last section
        # today, and a `return` here would silently skip a fifth one added
        # below it.
        out["conquest"] = _formation_error(errors["conquest"], mode="conquest")
    else:
        try:
            conquest_result = optimize_conquest(
                heroes,
                catalog,
                conquest_roles,
                gear=gear,
                gear_profile=gear_profile_arena,
                governor=governor,
            )
            out["conquest"] = conquest_result.to_dict()
            if conquest_result.status != "Optimal":
                errors["conquest"] = f"status={conquest_result.status}"
        except _DOMAIN_ERRORS as exc:
            errors["conquest"] = str(exc)
            out["conquest"] = _formation_error(str(exc), mode="conquest")
        except Exception as exc:  # noqa: BLE001
            logger.exception("conquest optimize failed")
            errors["conquest"] = f"internal error: {exc}"
            out["conquest"] = _formation_error(errors["conquest"], mode="conquest")
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


def run_radiant_optimize(
    heroes: list[HeroRecord],
    *,
    governor_bonuses: GovernorTroopBonuses,
    gear: list[GearRecord] | None = None,
    config_root: Path | None = None,
    troops_path: Path | None = None,
    active_marches: int = 2,
    floor: int | None = None,
    enemy_ratio: dict[str, float] | None = None,
    enemy_bonuses: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Dual-march Radiant Spire proxy from current inventory + governor gear."""
    from ks.heroes.optimize.radiant_spire import optimize_radiant

    root = (config_root or REPO_ROOT).expanduser().resolve()
    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    resolved_troops = (
        Path(troops_path).expanduser().resolve()
        if troops_path is not None
        else root / "config" / "troops.yaml"
    )
    troops = load_troops_config(resolved_troops)
    troop_stats = load_troop_stats(root / "config" / "troop_stats.yaml")
    raw_troops = yaml.safe_load(resolved_troops.read_text(encoding="utf-8")) or {}
    truegold = int(raw_troops.get("truegold", troop_stats.default_truegold))
    result = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=list(gear or ()),
        governor=governor_bonuses,
        troops=troops,
        troop_stats=troop_stats,
        active_marches=active_marches,
        truegold=truegold,
        floor=floor,
        floors_path=root / "config" / "mystic_trial" / "radiant_spire_floors.yaml",
        enemy_ratio=enemy_ratio,
        enemy_bonuses=enemy_bonuses,
    )
    return result.to_dict()


def run_coliseum_optimize(
    heroes: list[HeroRecord],
    *,
    governor_bonuses: GovernorTroopBonuses,
    gear: list[GearRecord] | None = None,
    config_root: Path | None = None,
    troops_path: Path | None = None,
) -> dict[str, Any]:
    """Single-march Coliseum proxy from heroes + gear (governor weight 0)."""
    from ks.heroes.optimize.mystic_trial.coliseum import optimize_coliseum

    root = (config_root or REPO_ROOT).expanduser().resolve()
    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    resolved_troops = (
        Path(troops_path).expanduser().resolve()
        if troops_path is not None
        else root / "config" / "troops.yaml"
    )
    troops = load_troops_config(resolved_troops)
    troop_stats = load_troop_stats(root / "config" / "troop_stats.yaml")
    raw_troops = yaml.safe_load(resolved_troops.read_text(encoding="utf-8")) or {}
    truegold = int(raw_troops.get("truegold", troop_stats.default_truegold))
    result = optimize_coliseum(
        heroes,
        catalog,
        gear_pieces=list(gear or ()),
        governor=governor_bonuses,
        troops=troops,
        troop_stats=troop_stats,
        truegold=truegold,
        room_path=root / "config" / "mystic_trial" / "coliseum.yaml",
    )
    return result.to_dict()


def run_molten_optimize(
    heroes: list[HeroRecord],
    *,
    governor_bonuses: GovernorTroopBonuses,
    gear: list[GearRecord] | None = None,
    config_root: Path | None = None,
    troops_path: Path | None = None,
) -> dict[str, Any]:
    """Single-march Molten Fort proxy — governor-primary, light hero weight."""
    from ks.heroes.optimize.mystic_trial.molten import optimize_molten

    root = (config_root or REPO_ROOT).expanduser().resolve()
    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    resolved_troops = (
        Path(troops_path).expanduser().resolve()
        if troops_path is not None
        else root / "config" / "troops.yaml"
    )
    troops = load_troops_config(resolved_troops)
    troop_stats = load_troop_stats(root / "config" / "troop_stats.yaml")
    raw_troops = yaml.safe_load(resolved_troops.read_text(encoding="utf-8")) or {}
    truegold = int(raw_troops.get("truegold", troop_stats.default_truegold))
    result = optimize_molten(
        heroes,
        catalog,
        gear_pieces=list(gear or ()),
        governor=governor_bonuses,
        troops=troops,
        troop_stats=troop_stats,
        truegold=truegold,
        room_path=root / "config" / "mystic_trial" / "molten_fort.yaml",
    )
    return result.to_dict()
