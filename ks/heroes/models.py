from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HeroStats:
    """Parsed Conquest ints and Expedition percent bonuses."""

    conquest: dict[str, int] = field(default_factory=dict)
    expedition: dict[str, float] = field(default_factory=dict)
    raw_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "conquest": dict(self.conquest),
            "expedition": dict(self.expedition),
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HeroStats | None:
        if not data:
            return None
        return cls(
            conquest={str(k): int(v) for k, v in (data.get("conquest") or {}).items()},
            expedition={
                str(k): float(v) for k, v in (data.get("expedition") or {}).items()
            },
            raw_text=data.get("raw_text"),
        )


@dataclass(frozen=True)
class SkillRecord:
    slot: int
    name: str | None = None
    level: int | None = None
    description: str | None = None
    upgrade_preview: str | None = None
    raw_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "name": self.name,
            "level": self.level,
            "description": self.description,
            "upgrade_preview": self.upgrade_preview,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRecord:
        return cls(
            slot=int(data["slot"]),
            name=data.get("name"),
            level=int(data["level"]) if data.get("level") is not None else None,
            description=data.get("description"),
            upgrade_preview=data.get("upgrade_preview"),
            raw_text=data.get("raw_text"),
        )


@dataclass(frozen=True)
class HeroRecord:
    name: str
    power: int | None = None
    rarity: str | None = None
    troop_type: str | None = None
    escorts: int | None = None
    stars: int | None = None
    stats: HeroStats | None = None
    skills: tuple[SkillRecord, ...] = ()
    roster_page: int = 0
    roster_index: int = 0
    scraped_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "power": self.power,
            "rarity": self.rarity,
            "troop_type": self.troop_type,
            "escorts": self.escorts,
            "stars": self.stars,
            "stats": self.stats.to_dict() if self.stats else None,
            "skills": [s.to_dict() for s in self.skills],
            "roster_page": self.roster_page,
            "roster_index": self.roster_index,
            "scraped_at": self.scraped_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeroRecord:
        skills_raw = data.get("skills") or []
        return cls(
            name=str(data["name"]),
            power=int(data["power"]) if data.get("power") is not None else None,
            rarity=data.get("rarity"),
            troop_type=data.get("troop_type"),
            escorts=int(data["escorts"]) if data.get("escorts") is not None else None,
            stars=int(data["stars"]) if data.get("stars") is not None else None,
            stats=HeroStats.from_dict(data.get("stats")),
            skills=tuple(SkillRecord.from_dict(s) for s in skills_raw),
            roster_page=int(data.get("roster_page") or 0),
            roster_index=int(data.get("roster_index") or 0),
            scraped_at=str(data.get("scraped_at") or ""),
        )
