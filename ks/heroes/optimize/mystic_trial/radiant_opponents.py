"""Persist Radiant Spire opponents by stage · round · march slot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ks.heroes.optimize.mystic_trial.floors import parse_enemy_bonuses
from ks.heroes.optimize.mystic_trial.ratios import TROOP_TYPES, normalize_ratio

STORE_VERSION = 1
MARCH_SLOTS = 2
DEFAULT_EVENT_TROOP_TIER = 10
DEFAULT_EVENT_MARCH_SIZE = 250_000


def default_player_event_troops(
    *,
    tier: int | None = None,
    march_size: int | None = None,
) -> dict[str, int]:
    """UI / solver defaults when stage·round has no saved override."""
    t = DEFAULT_EVENT_TROOP_TIER if tier is None else int(tier)
    size = DEFAULT_EVENT_MARCH_SIZE if march_size is None else int(march_size)
    return parse_player_event_troops({"tier": t, "march_size": size})


def parse_player_event_troops(raw: Any) -> dict[str, int]:
    """Validate ``{tier, march_size}`` for event-borrowed player troops."""
    if not isinstance(raw, dict):
        raise ValueError(
            f"player_event_troops must be a mapping; got {type(raw).__name__}"
        )
    tier = _as_int(raw.get("tier"), field="player_event_troops.tier")
    if tier < 1 or tier > 11:
        raise ValueError(f"player_event_troops.tier must be 1–11; got {tier}")
    march_size = _as_int(raw.get("march_size"), field="player_event_troops.march_size")
    if march_size < 1:
        raise ValueError(
            f"player_event_troops.march_size must be >= 1; got {march_size}"
        )
    return {"tier": tier, "march_size": march_size}


def default_levels() -> dict[str, int]:
    return {t: 6 for t in TROOP_TYPES}


def default_counts() -> dict[str, int]:
    return {t: 0 for t in TROOP_TYPES}


def empty_march() -> dict[str, Any]:
    from ks.heroes.optimize.mystic_trial.floors import empty_enemy_bonuses

    return {
        "hero_names": ["", "", ""],
        "hero_level": None,
        "gear_enhancement": None,
        "levels": default_levels(),
        "counts": default_counts(),
        "bonuses": empty_enemy_bonuses(),
    }


def opponents_path(governor_dir: Path, room: str = "radiant") -> Path:
    """YAML under governor ``mystic_trial/``; ``room`` is radiant or coliseum."""
    key = str(room or "radiant").strip().lower().replace(" ", "_")
    if key in ("radiant_spire", "radiant"):
        key = "radiant"
    elif key in ("coliseum",):
        key = "coliseum"
    else:
        raise ValueError(f"unsupported mystic opponents room {room!r}")
    return (
        Path(governor_dir).expanduser().resolve()
        / "mystic_trial"
        / f"{key}_opponents.yaml"
    )


def _as_int(value: Any, *, field: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer; got {value!r}") from exc
    return n


def _parse_levels(raw: Any) -> dict[str, int]:
    out = default_levels()
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise ValueError(f"levels must be a mapping; got {type(raw).__name__}")
    for troop in TROOP_TYPES:
        if troop not in raw:
            continue
        level = _as_int(raw[troop], field=f"levels.{troop}")
        if level < 1 or level > 11:
            raise ValueError(f"levels.{troop} must be 1–11; got {level}")
        out[troop] = level
    return out


def _parse_counts(raw: Any) -> dict[str, int]:
    out = default_counts()
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise ValueError(f"counts must be a mapping; got {type(raw).__name__}")
    for troop in TROOP_TYPES:
        if troop not in raw:
            continue
        count = _as_int(raw[troop], field=f"counts.{troop}")
        if count < 0:
            raise ValueError(f"counts.{troop} must be >= 0; got {count}")
        out[troop] = count
    return out


def _parse_hero_names(raw: Any) -> list[str]:
    names = ["", "", ""]
    if raw is None:
        return names
    if not isinstance(raw, list):
        raise ValueError(f"hero_names must be a list; got {type(raw).__name__}")
    for i, item in enumerate(raw[:3]):
        names[i] = str(item or "").strip()
    return names


def parse_march(raw: Any) -> dict[str, Any]:
    if raw is None:
        return empty_march()
    if not isinstance(raw, dict):
        raise ValueError(f"march must be a mapping; got {type(raw).__name__}")
    hero_level = raw.get("hero_level")
    gear_enh = raw.get("gear_enhancement")
    parsed_level = None if hero_level is None else _as_int(hero_level, field="hero_level")
    parsed_gear = (
        None if gear_enh is None else _as_int(gear_enh, field="gear_enhancement")
    )
    if parsed_level is not None and parsed_level < 1:
        raise ValueError(f"hero_level must be >= 1; got {parsed_level}")
    if parsed_gear is not None and parsed_gear < 0:
        raise ValueError(f"gear_enhancement must be >= 0; got {parsed_gear}")
    return {
        "hero_names": _parse_hero_names(raw.get("hero_names")),
        "hero_level": parsed_level,
        "gear_enhancement": parsed_gear,
        "levels": _parse_levels(raw.get("levels")),
        "counts": _parse_counts(raw.get("counts")),
        "bonuses": parse_enemy_bonuses(raw.get("bonuses")),
    }


def _two_marches(raw_list: Any) -> list[dict[str, Any]]:
    marches = [empty_march(), empty_march()]
    if raw_list is None:
        return marches
    if not isinstance(raw_list, list):
        raise ValueError(f"marches must be a list; got {type(raw_list).__name__}")
    for i, item in enumerate(raw_list[:MARCH_SLOTS]):
        marches[i] = parse_march(item)
    return marches


def load_store(path: Path) -> dict[str, Any]:
    """Return normalized store dict; missing file → empty stages."""
    p = Path(path)
    if not p.is_file():
        return {"version": STORE_VERSION, "stages": {}}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"radiant opponents file must be a mapping; got {type(raw).__name__}")
    stages_raw = raw.get("stages") or {}
    if not isinstance(stages_raw, dict):
        raise ValueError("stages must be a mapping")
    stages: dict[str, dict[str, dict[str, Any]]] = {}
    for stage_key, rounds_raw in stages_raw.items():
        if not isinstance(rounds_raw, dict):
            raise ValueError(f"stages[{stage_key!r}] must be a mapping of rounds")
        rounds: dict[str, dict[str, Any]] = {}
        for round_key, entry in rounds_raw.items():
            if not isinstance(entry, dict):
                raise ValueError(
                    f"stages[{stage_key!r}][{round_key!r}] must be a mapping"
                )
            rounds[str(round_key)] = {
                "marches": _two_marches(entry.get("marches")),
                "player_bonuses": (
                    parse_enemy_bonuses(entry.get("player_bonuses"))
                    if entry.get("player_bonuses") is not None
                    else None
                ),
                "player_event_troops": (
                    parse_player_event_troops(entry.get("player_event_troops"))
                    if entry.get("player_event_troops") is not None
                    else None
                ),
            }
        stages[str(stage_key)] = rounds
    return {"version": int(raw.get("version", STORE_VERSION)), "stages": stages}


def save_store(path: Path, store: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": int(store.get("version", STORE_VERSION)),
        "stages": store.get("stages") or {},
    }
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    p.write_text(text, encoding="utf-8")


def get_stage_round(
    store: dict[str, Any], stage: int, round_no: int
) -> list[dict[str, Any]] | None:
    """Return two marches or None if that stage·round was never saved."""
    stages = store.get("stages") or {}
    rounds = stages.get(str(int(stage)))
    if not isinstance(rounds, dict):
        return None
    entry = rounds.get(str(int(round_no)))
    if not isinstance(entry, dict):
        return None
    return _two_marches(entry.get("marches"))


def get_player_bonuses(
    store: dict[str, Any], stage: int, round_no: int
) -> dict[str, dict[str, float]] | None:
    """Battle-report formation bonuses for *your* marches, if saved."""
    stages = store.get("stages") or {}
    rounds = stages.get(str(int(stage)))
    if not isinstance(rounds, dict):
        return None
    entry = rounds.get(str(int(round_no)))
    if not isinstance(entry, dict):
        return None
    raw = entry.get("player_bonuses")
    if raw is None:
        return None
    return parse_enemy_bonuses(raw)


def get_player_event_troops(
    store: dict[str, Any], stage: int, round_no: int
) -> dict[str, int] | None:
    """Event-borrowed tier + march size for a stage·round, if saved."""
    stages = store.get("stages") or {}
    rounds = stages.get(str(int(stage)))
    if not isinstance(rounds, dict):
        return None
    entry = rounds.get(str(int(round_no)))
    if not isinstance(entry, dict):
        return None
    raw = entry.get("player_event_troops")
    if raw is None:
        return None
    return parse_player_event_troops(raw)


def _entry_preserving(
    existing: Any,
    *,
    marches: list[dict[str, Any]] | None = None,
    player_bonuses: Any = ...,
    player_event_troops: Any = ...,
) -> dict[str, Any]:
    """Build a stage·round entry while preserving sibling fields."""
    base = existing if isinstance(existing, dict) else {}
    out: dict[str, Any] = {
        "marches": (
            marches
            if marches is not None
            else _two_marches(base.get("marches"))
        ),
    }
    bonuses = player_bonuses
    if bonuses is ...:
        bonuses = base.get("player_bonuses")
    if bonuses is not None:
        out["player_bonuses"] = parse_enemy_bonuses(bonuses)

    event_troops = player_event_troops
    if event_troops is ...:
        event_troops = base.get("player_event_troops")
    if event_troops is not None:
        out["player_event_troops"] = parse_player_event_troops(event_troops)
    return out


def upsert_player_bonuses(
    store: dict[str, Any],
    *,
    stage: int,
    round_no: int,
    bonuses: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Save your battle-report formation totals for a stage·round."""
    stage_s = str(int(stage))
    round_s = str(int(round_no))
    stages = dict(store.get("stages") or {})
    rounds = dict(stages.get(stage_s) or {})
    existing = rounds.get(round_s) or {}
    rounds[round_s] = _entry_preserving(
        existing, player_bonuses=parse_enemy_bonuses(bonuses)
    )
    stages[stage_s] = rounds
    return {"version": STORE_VERSION, "stages": stages}


def upsert_player_event_troops(
    store: dict[str, Any],
    *,
    stage: int,
    round_no: int,
    event_troops: dict[str, int],
) -> dict[str, Any]:
    """Save event-borrowed tier + march size for a stage·round."""
    stage_s = str(int(stage))
    round_s = str(int(round_no))
    stages = dict(store.get("stages") or {})
    rounds = dict(stages.get(stage_s) or {})
    existing = rounds.get(round_s) or {}
    rounds[round_s] = _entry_preserving(
        existing,
        player_event_troops=parse_player_event_troops(event_troops),
    )
    stages[stage_s] = rounds
    return {"version": STORE_VERSION, "stages": stages}


def upsert_march(
    store: dict[str, Any],
    *,
    stage: int,
    round_no: int,
    slot: int,
    march: dict[str, Any],
) -> dict[str, Any]:
    """Upsert one march slot; ensure both slots exist. Returns updated store."""
    if slot not in (0, 1):
        raise ValueError(f"slot must be 0 or 1; got {slot}")
    stage_s = str(int(stage))
    round_s = str(int(round_no))
    stages = dict(store.get("stages") or {})
    rounds = dict(stages.get(stage_s) or {})
    existing = rounds.get(round_s) or {}
    marches = _two_marches(existing.get("marches") if isinstance(existing, dict) else None)
    marches[slot] = parse_march(march)
    rounds[round_s] = _entry_preserving(existing, marches=marches)
    stages[stage_s] = rounds
    return {"version": STORE_VERSION, "stages": stages}


def ratio_from_counts(counts: dict[str, int]) -> dict[str, float] | None:
    total = sum(int(counts.get(t, 0) or 0) for t in TROOP_TYPES)
    if total <= 0:
        return None
    return normalize_ratio({t: float(counts.get(t, 0) or 0) for t in TROOP_TYPES})


def merge_saved_into_opponent(
    opponent: dict[str, Any] | None,
    saved_marches: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Overlay saved levels/counts/bonuses onto built opponent panel marches.

    When ``opponent`` is None (Coliseum / no floor stub), builds a panel from
    saved marches alone so the UI still has Opponent 1/2 chips to edit.
    """
    if not saved_marches:
        return opponent
    out = dict(opponent) if opponent is not None else {}
    built = list(out.get("marches") or [])
    merged: list[dict[str, Any]] = []
    for i in range(MARCH_SLOTS):
        base = dict(built[i]) if i < len(built) and isinstance(built[i], dict) else {
            "hero_names": ["", "", ""],
            "capacity": 0,
        }
        saved = saved_marches[i] if i < len(saved_marches) else empty_march()
        counts = dict(saved["counts"])
        levels = dict(saved["levels"])
        bonuses = {t: dict(saved["bonuses"][t]) for t in TROOP_TYPES}
        ratio = ratio_from_counts(counts)
        names = list(saved.get("hero_names") or ["", "", ""])
        while len(names) < 3:
            names.append("")
        row = {
            **base,
            "hero_names": names[:3],
            "hero_level": saved.get("hero_level"),
            "gear_enhancement": saved.get("gear_enhancement"),
            "levels": levels,
            "counts": counts,
            "bonuses": bonuses,
        }
        if ratio is not None:
            row["ratio"] = ratio
        merged.append(row)
    out["marches"] = merged
    # Panel-level bonuses mirror march 0 for chips that still read opp.bonuses.
    if merged:
        out["bonuses"] = {t: dict(merged[0]["bonuses"][t]) for t in TROOP_TYPES}
    out["saved"] = True
    return out


__all__ = [
    "DEFAULT_EVENT_MARCH_SIZE",
    "DEFAULT_EVENT_TROOP_TIER",
    "MARCH_SLOTS",
    "STORE_VERSION",
    "default_counts",
    "default_levels",
    "default_player_event_troops",
    "empty_march",
    "get_player_bonuses",
    "get_player_event_troops",
    "get_stage_round",
    "load_store",
    "merge_saved_into_opponent",
    "opponents_path",
    "parse_march",
    "parse_player_event_troops",
    "ratio_from_counts",
    "save_store",
    "upsert_march",
    "upsert_player_bonuses",
    "upsert_player_event_troops",
]
