"""Append-only lifetime Power-i observation log (per hero).

Curve-sharing / game-table fit is a separate story — this only stores evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.models import HeroRecord, SkillRecord
from ks.heroes.power_breakdown import PowerBreakdown, breakdown_sum_ok


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def history_path(history_dir: Path, hero_name: str) -> Path:
    return Path(history_dir) / f"{_slug(hero_name)}.yaml"


@dataclass(frozen=True)
class PowerHistoryPoint:
    """One Power-i sample at a progression state."""

    scraped_at: str
    level: int | None
    stars: int | None
    pellets: int | None
    skills: tuple[tuple[int, int | None], ...]  # (slot, level)
    from_level: int | None
    from_stars: int | None
    from_skills: int | None
    gear_strength: int | None
    hero_power: int | None
    sum_ok: bool

    def identity_key(self) -> tuple[Any, ...]:
        """Fields compared for append-if-changed."""
        return (
            self.level,
            self.stars,
            self.pellets,
            self.skills,
            self.from_level,
            self.from_stars,
            self.from_skills,
            self.gear_strength,
            self.hero_power,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scraped_at": self.scraped_at,
            "level": self.level,
            "stars": self.stars,
            "pellets": self.pellets,
            "skills": [{"slot": s, "level": lv} for s, lv in self.skills],
            "from_level": self.from_level,
            "from_stars": self.from_stars,
            "from_skills": self.from_skills,
            "gear_strength": self.gear_strength,
            "hero_power": self.hero_power,
            "sum_ok": self.sum_ok,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PowerHistoryPoint:
        skills_raw = data.get("skills") or []
        skills = tuple(
            (int(s["slot"]), int(s["level"]) if s.get("level") is not None else None)
            for s in skills_raw
        )
        return cls(
            scraped_at=str(data.get("scraped_at") or ""),
            level=int(data["level"]) if data.get("level") is not None else None,
            stars=int(data["stars"]) if data.get("stars") is not None else None,
            pellets=int(data["pellets"]) if data.get("pellets") is not None else None,
            skills=skills,
            from_level=int(data["from_level"])
            if data.get("from_level") is not None
            else None,
            from_stars=int(data["from_stars"])
            if data.get("from_stars") is not None
            else None,
            from_skills=int(data["from_skills"])
            if data.get("from_skills") is not None
            else None,
            gear_strength=int(data["gear_strength"])
            if data.get("gear_strength") is not None
            else None,
            hero_power=int(data["hero_power"])
            if data.get("hero_power") is not None
            else None,
            sum_ok=bool(data.get("sum_ok")),
        )


def point_from_hero_and_breakdown(
    hero: HeroRecord,
    breakdown: PowerBreakdown,
    *,
    scraped_at: str | None = None,
) -> PowerHistoryPoint:
    """Build a history point from a store hero + Power-i OCR."""
    skills = tuple(
        (int(s.slot), s.level if isinstance(s, SkillRecord) else None)
        for s in (hero.skills or ())
    )
    stamp = scraped_at or hero.scraped_at or ""
    return PowerHistoryPoint(
        scraped_at=stamp,
        level=hero.level,
        stars=hero.stars,
        pellets=hero.pellets,
        skills=skills,
        from_level=breakdown.from_level,
        from_stars=breakdown.from_stars,
        from_skills=breakdown.from_skills,
        gear_strength=breakdown.gear_strength,
        hero_power=breakdown.hero_power,
        sum_ok=breakdown_sum_ok(breakdown),
    )


def load_points(history_dir: Path, hero_name: str) -> list[PowerHistoryPoint]:
    path = history_path(history_dir, hero_name)
    if not path.is_file():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [PowerHistoryPoint.from_dict(p) for p in (payload.get("points") or [])]


def append_if_changed(
    history_dir: Path,
    hero_name: str,
    point: PowerHistoryPoint,
) -> bool:
    """Append ``point`` when it differs from the last stored point.

    Returns True when a new point was written.
    """
    if not hero_name or not hero_name.strip():
        raise ValueError("hero_name must be non-empty")
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_path(history_dir, hero_name)
    existing = load_points(history_dir, hero_name)
    if existing and existing[-1].identity_key() == point.identity_key():
        return False
    existing.append(point)
    path.write_text(
        yaml.safe_dump(
            {
                "hero": hero_name,
                "count": len(existing),
                "points": [p.to_dict() for p in existing],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return True


def record_breakdown_for_hero(
    history_dir: Path,
    hero: HeroRecord,
    breakdown: PowerBreakdown,
) -> bool:
    """Convenience: build point from hero+breakdown and append if changed."""
    point = point_from_hero_and_breakdown(hero, breakdown)
    return append_if_changed(history_dir, hero.name, point)
