"""Load Mystic Trial room configuration from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from ks.heroes.optimize.mystic_trial.ratios import TROOP_TYPES, normalize_ratio

RoomFocus = Literal["all", "governor", "heroes_gear"]


@dataclass(frozen=True)
class RoomConfig:
    id: str
    label: str
    focus: RoomFocus
    seed_ratio: dict[str, float]
    published_ratios: tuple[dict[str, float], ...]
    active_marches: int = 1
    schema_marches: int = 1


def _ratio_map(raw: Any, *, field: str) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError(f"{field} must be a mapping of troop → fraction")
    return normalize_ratio({str(k): float(v) for k, v in raw.items()})


def load_room(path: Path | str) -> RoomConfig:
    p = Path(path).expanduser().resolve()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"room config must be a mapping: {p}")
    room_id = str(raw.get("id") or p.stem)
    focus = str(raw.get("focus") or "all").strip().lower()
    if focus not in ("all", "governor", "heroes_gear"):
        raise ValueError(f"unknown focus {focus!r} in {p}; want all|governor|heroes_gear")
    seed = _ratio_map(raw.get("seed_ratio"), field="seed_ratio")
    published_raw = raw.get("published_ratios") or [seed]
    if not isinstance(published_raw, list) or not published_raw:
        raise ValueError(f"published_ratios must be a non-empty list in {p}")
    published = tuple(_ratio_map(item, field="published_ratios[]") for item in published_raw)
    # Ensure seed is first published entry for search.
    if published[0] != seed:
        published = (seed,) + published
    active = int(raw.get("active_marches", 1))
    schema = int(raw.get("schema_marches", active))
    if active < 1 or active > 3:
        raise ValueError(f"active_marches must be 1–3; got {active}")
    if schema < active:
        raise ValueError(f"schema_marches must be >= active_marches; got {schema} < {active}")
    for t in TROOP_TYPES:
        assert t in seed, f"seed_ratio missing {t}"
    return RoomConfig(
        id=room_id,
        label=str(raw.get("label") or room_id),
        focus=focus,  # type: ignore[arg-type]
        seed_ratio=seed,
        published_ratios=published,
        active_marches=active,
        schema_marches=schema,
    )
