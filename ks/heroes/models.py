from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ks.heroes.assurance import FieldAssurance, assurance_from_dict, assurance_to_dict


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
class ExclusiveGearRecord:
    """Player-owned exclusive gear / widget progression."""

    level: int | None = None
    max_level: int = 10
    widget_name: str | None = None
    widget_type: str | None = None
    source: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "max_level": self.max_level,
            "widget_name": self.widget_name,
            "widget_type": self.widget_type,
            "source": self.source,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExclusiveGearRecord | None:
        if not data:
            return None
        level = data.get("level")
        max_level = data.get("max_level")
        return cls(
            level=int(level) if level is not None else None,
            max_level=int(max_level) if max_level is not None else 10,
            widget_name=data.get("widget_name"),
            widget_type=data.get("widget_type"),
            source=data.get("source"),
            updated_at=data.get("updated_at"),
        )


@dataclass(frozen=True)
class SkillRecord:
    slot: int
    name: str | None = None
    level: int | None = None
    description: str | None = None
    upgrade_preview: str | None = None
    current_bonus: float | None = None
    raw_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "name": self.name,
            "level": self.level,
            "description": self.description,
            "upgrade_preview": self.upgrade_preview,
            "current_bonus": self.current_bonus,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRecord:
        bonus = data.get("current_bonus")
        return cls(
            slot=int(data["slot"]),
            name=data.get("name"),
            level=int(data["level"]) if data.get("level") is not None else None,
            description=data.get("description"),
            upgrade_preview=data.get("upgrade_preview"),
            current_bonus=float(bonus) if bonus is not None else None,
            raw_text=data.get("raw_text"),
        )


@dataclass(frozen=True)
class HeroRecord:
    name: str
    power: int | None = None
    level: int | None = None
    rarity: str | None = None
    troop_type: str | None = None
    escorts: int | None = None
    stars: int | None = None
    pellets: int | None = None
    stats: HeroStats | None = None
    skills: tuple[SkillRecord, ...] = ()
    roster_page: int = 0
    roster_index: int = 0
    scraped_at: str = ""
    name_screenshot: str | None = None
    assurance: dict[str, FieldAssurance] = field(default_factory=dict)
    exclusive_gear: ExclusiveGearRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "power": self.power,
            "level": self.level,
            "rarity": self.rarity,
            "troop_type": self.troop_type,
            "escorts": self.escorts,
            "stars": self.stars,
            "pellets": self.pellets,
            "stats": self.stats.to_dict() if self.stats else None,
            "skills": [s.to_dict() for s in self.skills],
            "roster_page": self.roster_page,
            "roster_index": self.roster_index,
            "scraped_at": self.scraped_at,
            "name_screenshot": self.name_screenshot,
            "assurance": assurance_to_dict(self.assurance),
            "exclusive_gear": (
                self.exclusive_gear.to_dict() if self.exclusive_gear else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeroRecord:
        skills_raw = data.get("skills") or []
        return cls(
            name=str(data["name"]),
            power=int(data["power"]) if data.get("power") is not None else None,
            level=int(data["level"]) if data.get("level") is not None else None,
            rarity=data.get("rarity"),
            troop_type=data.get("troop_type"),
            escorts=int(data["escorts"]) if data.get("escorts") is not None else None,
            stars=int(data["stars"]) if data.get("stars") is not None else None,
            pellets=int(data["pellets"]) if data.get("pellets") is not None else None,
            stats=HeroStats.from_dict(data.get("stats")),
            skills=tuple(SkillRecord.from_dict(s) for s in skills_raw),
            roster_page=int(data.get("roster_page") or 0),
            roster_index=int(data.get("roster_index") or 0),
            scraped_at=str(data.get("scraped_at") or ""),
            name_screenshot=data.get("name_screenshot"),
            assurance=assurance_from_dict(data.get("assurance") or {}),
            exclusive_gear=ExclusiveGearRecord.from_dict(data.get("exclusive_gear")),
        )
