from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TroopsConfig:
    """Owned troops. Totals drive the ILP; optional per-level maps are for fill order."""

    infantry: int
    cavalry: int
    archers: int
    march_capacity: int
    infantry_levels: tuple[tuple[int, int], ...] = ()
    cavalry_levels: tuple[tuple[int, int], ...] = ()
    archers_levels: tuple[tuple[int, int], ...] = ()

    def owned(self, troop_type: str) -> int:
        key = troop_type.strip().lower()
        if key in ("infantry", "i"):
            return self.infantry
        if key in ("cavalry", "c"):
            return self.cavalry
        if key in ("archers", "archer", "a"):
            return self.archers
        raise ValueError(f"unknown troop type: {troop_type!r}")

    def levels(self, troop_type: str) -> dict[int, int]:
        key = troop_type.strip().lower()
        raw: tuple[tuple[int, int], ...]
        if key in ("infantry", "i"):
            raw = self.infantry_levels
        elif key in ("cavalry", "c"):
            raw = self.cavalry_levels
        elif key in ("archers", "archer", "a"):
            raw = self.archers_levels
        else:
            raise ValueError(f"unknown troop type: {troop_type!r}")
        return {int(level): int(count) for level, count in raw}

    @property
    def max_level(self) -> int:
        levels = (
            [lv for lv, _ in self.infantry_levels]
            + [lv for lv, _ in self.cavalry_levels]
            + [lv for lv, _ in self.archers_levels]
        )
        return max(levels) if levels else 1

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "infantry": self.infantry,
            "cavalry": self.cavalry,
            "archers": self.archers,
            "march_capacity": self.march_capacity,
        }
        if self.infantry_levels or self.cavalry_levels or self.archers_levels:
            out["by_level"] = {
                "infantry": dict(self.infantry_levels),
                "cavalry": dict(self.cavalry_levels),
                "archers": dict(self.archers_levels),
            }
        return out


@dataclass(frozen=True)
class EffectTag:
    kind: str
    max_value: float
    applies_to: str = "expedition"  # expedition | widget | talent
    effect_op: int | None = None  # community SkillMod identifier
    first_expedition: bool = False  # joiner-eligible first expedition skill
    # Independent chance the effect fires (e.g. Helga Oath of Guardian).
    # None = always-on. Incoming-damage kinds use a miss/hit mixture, not
    # ``magnitude * proc_chance`` stacked as a second multiplicative DR layer.
    proc_chance: float | None = None


@dataclass(frozen=True)
class CatalogSkill:
    """Named skill row from hero_catalog (static); live levels live on HeroRecord."""

    slot: int
    name: str
    family: str  # conquest | expedition | widget
    effect_kind: str | None = None
    # Hybrid ladders: absolute values at levels 1..N (usually 5). When set,
    # leveled scoring uses ladder[level-1] instead of max_value * level/5.
    ladder: tuple[float, ...] | None = None
    hits_per_cast: int | None = None
    cast_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "slot": self.slot,
            "name": self.name,
            "family": self.family,
        }
        if self.effect_kind is not None:
            out["effect_kind"] = self.effect_kind
        if self.ladder is not None:
            out["ladder"] = list(self.ladder)
        if self.hits_per_cast is not None:
            out["hits_per_cast"] = self.hits_per_cast
        if self.cast_rate is not None:
            out["cast_rate"] = self.cast_rate
        return out


@dataclass(frozen=True)
class CatalogEntry:
    """Static hero semantics — single source of truth from hero_catalog.yaml.

    Live roster power/stars/skills live in scraped heroes.json; this entry is
    the shared identity + widget/effect/arena overlay used by recommend + arena.
    """

    name: str
    gen: int | None = None
    troop: str | None = None
    rarity: str | None = None
    widget_type: str | None = None  # attack | defense | none
    widget_name: str | None = None
    widget_march_skill: str | None = None
    rally_widget_priority: int | None = None  # 1..5 stars
    garrison_widget_priority: int | None = None
    rally_tier: str | None = None
    garrison_tier: str | None = None
    joiner_tier: str | None = None
    effects: tuple[EffectTag, ...] = ()
    skills: tuple[CatalogSkill, ...] = ()
    # Arena ILP hints (formerly config/arena_roles.yaml heroes:)
    arena_role: str | None = None
    arena_value: float | None = None
    arena_tags: tuple[str, ...] = ()
    obtain: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class EventProfile:
    name: str
    sources: tuple[str, ...] = ()
    mode_kind_weights: dict[str, dict[str, float]] | None = None
    effect_op_weights: dict[str, dict[int, float]] | None = None


@dataclass(frozen=True)
class SurvivalFill:
    """PvP troop fill: infantry wall from β√capacity, then √n leftover.

    ``infantry_beta`` is calibrated so 50% infantry at an 80_280 march:
    β = 0.5 * √80280 ≈ 141.67. Larger marches then want a thinner wall.
    """

    infantry_beta: float
    infantry_max_frac: float = 0.6
    infantry_min_frac: float = 0.0
    min_type_frac: float = 0.05


@dataclass(frozen=True)
class Scenario:
    mode: str
    combat_rate: float
    minutes_held: float = 0.0
    personal_rate: float = 0.0
    p_first: float = 0.0
    first_bonus: float = 0.0
    loot_expected: float = 0.0
    enemy_power_scale: float = 100_000.0
    formation_weights: dict[str, float] | None = None
    survival_fill: SurvivalFill | None = None
    require_widget: str | None = None  # attack | defense | None


@dataclass(frozen=True)
class ModeSolution:
    mode: str
    hero_names: tuple[str, ...]
    troops: dict[str, int]
    effective_capacity: int
    expected_personal_points: float
    breakdown: dict[str, float]
    status: str = "Optimal"


@dataclass(frozen=True)
class RecommendResult:
    recommended_mode: str
    heroes: tuple[dict[str, Any], ...]
    troops: dict[str, int]
    ratios: dict[str, float]
    effective_capacity: int
    expected_personal_points: float
    breakdown: dict[str, float]
    alternatives: tuple[dict[str, Any], ...] = ()
    troops_by_level: dict[str, dict[int, int]] | None = None
    gear_assignment: dict[str, list[dict[str, Any]]] | None = None
    stat_family: str = "expedition"
    formation_totals: dict[str, Any] | None = None
    skillmod_detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "recommended_mode": self.recommended_mode,
            "heroes": list(self.heroes),
            "troops": dict(self.troops),
            "ratios": dict(self.ratios),
            "effective_capacity": self.effective_capacity,
            "expected_personal_points": self.expected_personal_points,
            "breakdown": dict(self.breakdown),
            "alternatives": list(self.alternatives),
            "stat_family": self.stat_family,
            "formation_totals": self.formation_totals,
        }
        if self.troops_by_level is not None:
            out["troops_by_level"] = {
                kind: {str(level): count for level, count in levels.items()}
                for kind, levels in self.troops_by_level.items()
            }
        if self.gear_assignment is not None:
            out["gear_assignment"] = self.gear_assignment
        if self.skillmod_detail is not None:
            out["skillmod_detail"] = self.skillmod_detail
        return out
