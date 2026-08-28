"""Governor gear piece records."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class LadderStep:
    tier: str
    stars: int
    attack_pct: float
    defense_pct: float
    power: int
    set_defense_pct: float
    set_attack_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "stars": self.stars,
            "attack_pct": self.attack_pct,
            "defense_pct": self.defense_pct,
            "power": self.power,
            "set_defense_pct": self.set_defense_pct,
            "set_attack_pct": self.set_attack_pct,
        }


@dataclass(frozen=True)
class SlotSpec:
    slot_id: str
    display_name: str
    troop: str
    pair: str


@dataclass(frozen=True)
class GovernorPiece:
    slot_id: str
    tier: str
    stars: int
    attack_pct: float = 0.0
    defense_pct: float = 0.0
    power: int = 0

    def with_ladder(self, step: LadderStep) -> GovernorPiece:
        return replace(
            self,
            tier=step.tier,
            stars=step.stars,
            attack_pct=float(step.attack_pct),
            defense_pct=float(step.defense_pct),
            power=int(step.power),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "tier": self.tier,
            "stars": self.stars,
            "attack_pct": self.attack_pct,
            "defense_pct": self.defense_pct,
            "power": self.power,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> GovernorPiece:
        if not isinstance(raw, Mapping):
            raise TypeError(f"GovernorPiece.from_dict expects mapping; got {type(raw)}")
        slot_id = str(raw.get("slot_id") or "").strip()
        if not slot_id:
            raise ValueError("GovernorPiece requires non-empty slot_id")
        return cls(
            slot_id=slot_id,
            tier=str(raw.get("tier") or "green"),
            stars=int(raw.get("stars") or 0),
            attack_pct=float(raw.get("attack_pct") or 0.0),
            defense_pct=float(raw.get("defense_pct") or 0.0),
            power=int(raw.get("power") or 0),
        )


@dataclass(frozen=True)
class GovernorTroopBonuses:
    attack_pct: dict[str, float]
    defense_pct: dict[str, float]
    set_attack_pct: float
    set_defense_pct: float
    set_tier: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_pct": dict(self.attack_pct),
            "defense_pct": dict(self.defense_pct),
            "set_attack_pct": self.set_attack_pct,
            "set_defense_pct": self.set_defense_pct,
            "set_tier": self.set_tier,
        }
