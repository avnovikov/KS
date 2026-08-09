"""Load and query ``config/governor_gear.yaml``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.governor_models import LadderStep, SlotSpec

_VALID_TROOPS = frozenset({"infantry", "cavalry", "archers"})


@dataclass(frozen=True)
class GovernorGearConfig:
    slots: dict[str, SlotSpec]
    ladder: tuple[LadderStep, ...]
    default_tier: str
    default_stars: int

    @property
    def path_hint(self) -> str:
        return "config/governor_gear.yaml"


def _default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "governor_gear.yaml"


def load_governor_gear_config(path: Path | str | None = None) -> GovernorGearConfig:
    cfg_path = Path(path) if path is not None else _default_path()
    if not cfg_path.is_file():
        raise FileNotFoundError(f"governor gear config missing: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"governor_gear.yaml must be a mapping; got {type(raw).__name__}")

    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, dict) or not slots_raw:
        raise ValueError("governor_gear.yaml must define non-empty slots")
    slots: dict[str, SlotSpec] = {}
    for slot_id, spec in slots_raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"slots.{slot_id} must be a mapping")
        troop = str(spec.get("troop") or "").strip().lower()
        if troop == "archer":
            troop = "archers"
        if troop not in _VALID_TROOPS:
            raise ValueError(f"slots.{slot_id}.troop must be infantry|cavalry|archers; got {troop!r}")
        pair = str(spec.get("pair") or "").strip()
        display = str(spec.get("display_name") or slot_id).strip()
        slots[str(slot_id)] = SlotSpec(
            slot_id=str(slot_id),
            display_name=display,
            troop=troop,
            pair=pair,
        )

    ladder_raw = raw.get("ladder")
    if not isinstance(ladder_raw, list) or not ladder_raw:
        raise ValueError("governor_gear.yaml must define a non-empty ladder list")
    ladder: list[LadderStep] = []
    for i, row in enumerate(ladder_raw):
        if not isinstance(row, dict):
            raise ValueError(f"ladder[{i}] must be a mapping")
        ladder.append(
            LadderStep(
                tier=str(row["tier"]),
                stars=int(row["stars"]),
                attack_pct=float(row["attack_pct"]),
                defense_pct=float(row["defense_pct"]),
                power=int(row["power"]),
                set_defense_pct=float(row.get("set_defense_pct", 0.0)),
                set_attack_pct=float(row.get("set_attack_pct", 0.0)),
            )
        )

    default = raw.get("default_step") or {}
    if not isinstance(default, dict):
        raise ValueError("default_step must be a mapping")
    return GovernorGearConfig(
        slots=slots,
        ladder=tuple(ladder),
        default_tier=str(default.get("tier") or ladder[0].tier),
        default_stars=int(default.get("stars") if default.get("stars") is not None else ladder[0].stars),
    )


def slot_troop(cfg: GovernorGearConfig, slot_id: str) -> str:
    if slot_id not in cfg.slots:
        raise KeyError(f"unknown governor slot {slot_id!r}")
    return cfg.slots[slot_id].troop


def ladder_index(cfg: GovernorGearConfig, tier: str, stars: int) -> int | None:
    for i, step in enumerate(cfg.ladder):
        if step.tier == tier and step.stars == stars:
            return i
    return None


def ladder_step(cfg: GovernorGearConfig, tier: str, stars: int) -> LadderStep | None:
    idx = ladder_index(cfg, tier, stars)
    if idx is None:
        return None
    return cfg.ladder[idx]


def next_ladder_step(cfg: GovernorGearConfig, tier: str, stars: int) -> LadderStep | None:
    idx = ladder_index(cfg, tier, stars)
    if idx is None:
        return None
    nxt = idx + 1
    if nxt >= len(cfg.ladder):
        return None
    return cfg.ladder[nxt]


def ladder_rank(cfg: GovernorGearConfig, tier: str) -> int:
    """Highest ladder index for any stars of this tier (for set-bonus preference)."""
    best = -1
    for i, step in enumerate(cfg.ladder):
        if step.tier == tier:
            best = i
    return best
