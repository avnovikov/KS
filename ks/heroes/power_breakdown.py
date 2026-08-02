"""Parse Kingshot Power-i breakdown (Level / Stars / Skills / Gear)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ks.heroes.parse import parse_int

_LINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hero_power", re.compile(r"hero\s*power\s*[:=]?\s*([\d,]+)", re.I)),
    ("from_level", re.compile(r"from\s*level\s*[:=]?\s*([\d,]+)", re.I)),
    ("from_stars", re.compile(r"from\s*stars?\s*[:=]?\s*([\d,]+)", re.I)),
    ("from_skills", re.compile(r"from\s*skills?\s*[:=]?\s*([\d,]+)", re.I)),
    ("gear_strength", re.compile(r"gear\s*strength\s*[:=]?\s*([\d,]+)", re.I)),
)

# Power-i tooltip panel on 1080×1920 (calibrated 2026-08-02).
BREAKDOWN_BOX = (172, 477, 734, 651)


@dataclass(frozen=True)
class PowerBreakdown:
    """OCR'd Power-i popup buckets."""

    hero_power: int | None = None
    from_level: int | None = None
    from_stars: int | None = None
    from_skills: int | None = None
    gear_strength: int | None = None
    raw_text: str = ""

    @property
    def naked(self) -> int | None:
        """Hero power without gear: Level + Stars + Skills."""
        parts = [self.from_level, self.from_stars, self.from_skills]
        if any(p is None for p in parts):
            return None
        return int(parts[0]) + int(parts[1]) + int(parts[2])  # type: ignore[arg-type]

    def naked_or_total_minus_gear(self) -> int | None:
        """Prefer component sum; else hero_power − gear when both present."""
        naked = self.naked
        if naked is not None:
            return naked
        if self.hero_power is not None and self.gear_strength is not None:
            return int(self.hero_power) - int(self.gear_strength)
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["naked"] = self.naked
        return d


def parse_power_breakdown(text: str) -> PowerBreakdown:
    """Parse Power-i OCR dump into labeled buckets."""
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")
    values: dict[str, int | None] = {key: None for key, _ in _LINE_PATTERNS}
    for key, pattern in _LINE_PATTERNS:
        match = pattern.search(text)
        if match:
            values[key] = parse_int(match.group(1))
    if values["hero_power"] is None:
        known = {
            values["from_level"],
            values["from_stars"],
            values["from_skills"],
            values["gear_strength"],
        }
        for match in re.finditer(r"([\d,]{5,})", text):
            n = parse_int(match.group(1))
            if n is None or n in known:
                continue
            values["hero_power"] = n
            break
    return PowerBreakdown(
        hero_power=values["hero_power"],
        from_level=values["from_level"],
        from_stars=values["from_stars"],
        from_skills=values["from_skills"],
        gear_strength=values["gear_strength"],
        raw_text=text,
    )


def breakdown_sum_ok(breakdown: PowerBreakdown, *, tol: int = 2) -> bool:
    """True when Level+Stars+Skills+(Gear or 0) ≈ Hero Power within tolerance."""
    if breakdown.hero_power is None:
        return False
    if (
        breakdown.from_level is None
        or breakdown.from_stars is None
        or breakdown.from_skills is None
    ):
        return False
    gear = 0 if breakdown.gear_strength is None else int(breakdown.gear_strength)
    total = (
        int(breakdown.from_level)
        + int(breakdown.from_stars)
        + int(breakdown.from_skills)
        + gear
    )
    return abs(total - int(breakdown.hero_power)) <= tol


def power_info_tap_from_power_box(*, x: int, y: int, w: int, h: int) -> tuple[int, int]:
    """Tap the ``i`` control: right side of the configured power OCR box."""
    return x + int(w * 0.80), y + h // 2
