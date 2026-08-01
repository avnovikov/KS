"""Assign best owned gear sets per troop class (fungible within class)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_store import GearStore
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.types import CatalogEntry

SLOTS = ("helmet", "chest", "gloves", "boots")

# early_game_growth — Bear Hunt listed in build_profiles.yaml
_DEFAULT_WEIGHTS = {
    "Infantry_Health": 1.5,
    "Infantry_Lethality": 0.7,
    "Cavalry_Health": 0.2,
    "Cavalry_Lethality": 0.4,
    "Archery_Health": 0.7,
    "Archery_Lethality": 1.4,
}

_SLOT_STAT = {
    ("infantry", "helmet"): ("lethality", "Infantry_Lethality"),
    ("infantry", "boots"): ("lethality", "Infantry_Lethality"),
    ("infantry", "chest"): ("health", "Infantry_Health"),
    ("infantry", "gloves"): ("health", "Infantry_Health"),
    ("cavalry", "helmet"): ("lethality", "Cavalry_Lethality"),
    ("cavalry", "boots"): ("lethality", "Cavalry_Lethality"),
    ("cavalry", "chest"): ("health", "Cavalry_Health"),
    ("cavalry", "gloves"): ("health", "Cavalry_Health"),
    ("archers", "helmet"): ("lethality", "Archery_Lethality"),
    ("archers", "boots"): ("lethality", "Archery_Lethality"),
    ("archers", "chest"): ("health", "Archery_Health"),
    ("archers", "gloves"): ("health", "Archery_Health"),
}

_NAME_SLOT_HINTS = (
    ("armet", "helmet"),
    ("faceplate", "helmet"),
    ("helm", "helmet"),
    ("shroud", "chest"),
    ("leatherwear", "chest"),
    ("breastplate", "chest"),
    ("gloves", "gloves"),
    ("bracers", "gloves"),
    ("gauntlet", "gloves"),
    ("boots", "boots"),
    ("greaves", "boots"),
    ("riders", "boots"),
)


def load_profile_weights(
    profile: str = "early_game_growth",
    *,
    path: Path | None = None,
) -> dict[str, float]:
    cfg_path = path or (
        Path(__file__).resolve().parents[3]
        / "config"
        / "hero_gear_optimizer"
        / "build_profiles.yaml"
    )
    if not cfg_path.is_file():
        return dict(_DEFAULT_WEIGHTS)
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    profiles = raw.get("profiles") or {}
    entry = profiles.get(profile) or {}
    weights = entry.get("weights") or {}
    if not weights:
        return dict(_DEFAULT_WEIGHTS)
    return {str(k): float(v) for k, v in weights.items()}


def infer_slot(piece: GearRecord) -> str | None:
    if piece.slot in SLOTS:
        return piece.slot
    name = (piece.name or "").lower()
    for needle, slot in _NAME_SLOT_HINTS:
        if needle in name:
            return slot
    return None


def piece_score(
    piece: GearRecord,
    *,
    profile: str = "early_game_growth",
    weights: dict[str, float] | None = None,
) -> float:
    troop = normalize_troop(piece.troop_type)
    slot = infer_slot(piece)
    wmap = weights or load_profile_weights(profile)
    if troop is None or slot is None:
        return float(piece.power or 0) / 100_000.0

    kind, weight_key = _SLOT_STAT[(troop, slot)]
    weight = float(wmap.get(weight_key, 1.0))
    stats = piece.stats
    pct = 0.0
    if stats is not None:
        if kind == "lethality" and stats.lethality is not None:
            pct = float(stats.lethality)
        elif kind == "health" and stats.health is not None:
            pct = float(stats.health)
        else:
            # Prefer matching expedition label if present.
            for label, value in (stats.expedition or {}).items():
                low = label.lower()
                if kind == "lethality" and "lethal" in low:
                    pct = float(value)
                    break
                if kind == "health" and "health" in low:
                    pct = float(value)
                    break
    if pct <= 0 and piece.power:
        return weight * (float(piece.power) / 100_000.0)
    return weight * pct


def best_sets_by_troop(
    pieces: list[GearRecord],
    *,
    profile: str = "early_game_growth",
) -> dict[str, dict[str, GearRecord]]:
    weights = load_profile_weights(profile)
    best: dict[str, dict[str, tuple[float, GearRecord]]] = {}
    for piece in pieces:
        troop = normalize_troop(piece.troop_type)
        slot = infer_slot(piece)
        if troop is None or slot is None:
            continue
        score = piece_score(piece, profile=profile, weights=weights)
        by_slot = best.setdefault(troop, {})
        prev = by_slot.get(slot)
        if prev is None or score > prev[0]:
            by_slot[slot] = (score, piece)
    return {
        troop: {slot: pair[1] for slot, pair in slots.items()}
        for troop, slots in best.items()
    }


def set_score(
    pieces_by_slot: dict[str, GearRecord],
    *,
    profile: str = "early_game_growth",
) -> float:
    weights = load_profile_weights(profile)
    return sum(
        piece_score(p, profile=profile, weights=weights)
        for p in pieces_by_slot.values()
    )


def gear_bonus_by_troop(
    pieces: list[GearRecord],
    *,
    profile: str = "early_game_growth",
) -> dict[str, float]:
    """Linear strength nudge from best transferable set per troop class."""
    sets = best_sets_by_troop(pieces, profile=profile)
    return {troop: set_score(slots, profile=profile) * 0.15 for troop, slots in sets.items()}


def assign_best_sets(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    pieces: list[GearRecord],
    *,
    selected: list[str] | None = None,
    profile: str = "early_game_growth",
) -> dict[str, dict[str, GearRecord]]:
    """Map selected heroes → best gear pieces for their troop class (shared pool)."""
    sets = best_sets_by_troop(pieces, profile=profile)
    names = selected if selected is not None else [h.name for h in heroes]
    by_name = {h.name: h for h in heroes}
    out: dict[str, dict[str, GearRecord]] = {}
    for name in names:
        troop = _hero_troop(name, by_name.get(name), catalog)
        if troop is None:
            out[name] = {}
            continue
        out[name] = dict(sets.get(troop) or {})
    return out


def assign_exclusive_sets(
    heroes: list[HeroRecord],
    catalog: dict[str, CatalogEntry],
    pieces: list[GearRecord],
    *,
    selected: list[str],
    priority: list[str] | None = None,
    profile: str = "early_game_growth",
) -> dict[str, dict[str, GearRecord]]:
    """Assign each inventory piece to at most one selected hero.

    Heroes earlier in ``priority`` (default: ``selected``) claim best matching
    pieces first — use carry/front order for Arena.
    """
    if not selected:
        return {}
    weights = load_profile_weights(profile)
    by_name = {h.name: h for h in heroes}
    order = list(priority) if priority else list(selected)
    # Keep every selected hero exactly once; append any missing at the end.
    seen: set[str] = set()
    ordered: list[str] = []
    for name in order + list(selected):
        if name in selected and name not in seen:
            ordered.append(name)
            seen.add(name)

    pool: dict[tuple[str, str], list[tuple[float, GearRecord]]] = {}
    for piece in pieces:
        troop = normalize_troop(piece.troop_type)
        slot = infer_slot(piece)
        if troop is None or slot is None:
            continue
        score = piece_score(piece, profile=profile, weights=weights)
        pool.setdefault((troop, slot), []).append((score, piece))
    for key in pool:
        pool[key].sort(key=lambda row: row[0], reverse=True)

    used: set[str] = set()
    out: dict[str, dict[str, GearRecord]] = {name: {} for name in ordered}
    for name in ordered:
        troop = _hero_troop(name, by_name.get(name), catalog)
        if troop is None:
            continue
        for slot in SLOTS:
            candidates = pool.get((troop, slot)) or []
            for _score, piece in candidates:
                if piece.piece_id in used:
                    continue
                out[name][slot] = piece
                used.add(piece.piece_id)
                break
    return out


def _hero_troop(
    name: str,
    hero: HeroRecord | None,
    catalog: dict[str, CatalogEntry],
) -> str | None:
    entry = catalog.get(name)
    if entry is not None:
        troop = normalize_troop(entry.troop)
        if troop is not None:
            return troop
    if hero is not None:
        return normalize_troop(hero.troop_type)
    return None


def load_gear_pieces(path: Path) -> list[GearRecord]:
    """Load from a gear.json file or a gear collect out_dir."""
    p = Path(path)
    if p.is_dir():
        return GearStore(p).all_pieces()
    raw = __import__("json").loads(p.read_text(encoding="utf-8"))
    items = raw.get("gear") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"gear file must contain a list; got {type(items).__name__}")
    return [GearRecord.from_dict(item) for item in items]


def assignment_to_dict(
    assigned: dict[str, dict[str, GearRecord]],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for hero, slots in assigned.items():
        rows: list[dict[str, Any]] = []
        for slot in SLOTS:
            piece = slots.get(slot)
            if piece is None:
                continue
            rows.append(
                {
                    "slot": slot,
                    "name": piece.name,
                    "rarity": piece.rarity,
                    "enhancement_level": piece.enhancement_level,
                    "mastery_level": piece.mastery_level,
                    "power": piece.power,
                    "piece_id": piece.piece_id,
                }
            )
        out[hero] = rows
    return out
