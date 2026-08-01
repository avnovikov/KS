"""Gear inventory piece records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GearStats:
    """Conquest flat bonuses, expedition percents, and convenience expedition fields."""

    conquest: dict[str, int] = field(default_factory=dict)
    expedition: dict[str, float] = field(default_factory=dict)
    attack: float | None = None
    defense: float | None = None
    health: float | None = None
    lethality: float | None = None
    raw_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "conquest": dict(self.conquest),
            "expedition": dict(self.expedition),
            "attack": self.attack,
            "defense": self.defense,
            "health": self.health,
            "lethality": self.lethality,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GearStats | None:
        if not data:
            return None
        return cls(
            conquest={str(k): int(v) for k, v in (data.get("conquest") or {}).items()},
            expedition={
                str(k): float(v) for k, v in (data.get("expedition") or {}).items()
            },
            attack=_opt_float(data.get("attack")),
            defense=_opt_float(data.get("defense")),
            health=_opt_float(data.get("health")),
            lethality=_opt_float(data.get("lethality")),
            raw_text=data.get("raw_text"),
        )


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


@dataclass(frozen=True)
class GearRecord:
    piece_id: str
    name: str | None = None
    troop_type: str | None = None
    slot: str | None = None
    rarity: str | None = None
    enhancement_level: int | None = None
    mastery_level: int | None = None
    power: int | None = None
    equipped: bool | None = None
    equipped_hero: str | None = None
    stats: GearStats | None = None
    raw_text: str | None = None
    inventory_page: int = 0
    inventory_index: int = 0
    scraped_at: str | None = None
    detail_screenshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "piece_id": self.piece_id,
            "name": self.name,
            "troop_type": self.troop_type,
            "slot": self.slot,
            "rarity": self.rarity,
            "enhancement_level": self.enhancement_level,
            "mastery_level": self.mastery_level,
            "power": self.power,
            "equipped": self.equipped,
            "equipped_hero": self.equipped_hero,
            "stats": self.stats.to_dict() if self.stats else None,
            "raw_text": self.raw_text,
            "inventory_page": self.inventory_page,
            "inventory_index": self.inventory_index,
            "scraped_at": self.scraped_at,
            "detail_screenshot": self.detail_screenshot,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GearRecord:
        if not isinstance(data, dict):
            raise TypeError(f"data must be dict; got {type(data).__name__}")
        piece_id = data.get("piece_id")
        if not piece_id:
            raise ValueError("piece_id is required")
        return cls(
            piece_id=str(piece_id),
            name=data.get("name"),
            troop_type=data.get("troop_type"),
            slot=data.get("slot"),
            rarity=data.get("rarity"),
            enhancement_level=_opt_int(data.get("enhancement_level")),
            mastery_level=_opt_int(data.get("mastery_level")),
            power=_opt_int(data.get("power")),
            equipped=data.get("equipped"),
            equipped_hero=data.get("equipped_hero"),
            stats=GearStats.from_dict(data.get("stats")),
            raw_text=data.get("raw_text"),
            inventory_page=int(data.get("inventory_page") or 0),
            inventory_index=int(data.get("inventory_index") or 0),
            scraped_at=data.get("scraped_at"),
            detail_screenshot=data.get("detail_screenshot"),
        )


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def make_piece_id(page: int, index: int) -> str:
    return f"page{page}-cell{index}"
