"""Academy / War Academy research troop percent bonuses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ks.heroes.optimize.mystic_trial.ratios import TROOP_TYPES

_STAT_KEYS: tuple[str, ...] = (
    "attack_pct",
    "defense_pct",
    "lethality_pct",
    "health_pct",
)


@dataclass(frozen=True)
class TroopResearchRow:
    """Percent-points for one troop type (same units as governor / expedition)."""

    attack_pct: float = 0.0
    defense_pct: float = 0.0
    lethality_pct: float = 0.0
    health_pct: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "attack_pct": float(self.attack_pct),
            "defense_pct": float(self.defense_pct),
            "lethality_pct": float(self.lethality_pct),
            "health_pct": float(self.health_pct),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> TroopResearchRow:
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise TypeError(
                f"TroopResearchRow expects mapping; got {type(raw).__name__}"
            )
        vals: dict[str, float] = {}
        for key in _STAT_KEYS:
            vals[key] = float(raw.get(key) or 0.0)
            if vals[key] < 0:
                raise ValueError(f"{key} must be >= 0; got {vals[key]}")
        return cls(**vals)


@dataclass(frozen=True)
class ResearchBonuses:
    """Per-troop + squad-wide research percent-points from Academy Battle.

    ``squad`` applies to every troop type (all-squad / universal Battle nodes).
    Effective maps from ``attack_pct()`` etc. already include squad.
    """

    troops: dict[str, TroopResearchRow]
    squad: TroopResearchRow = TroopResearchRow()
    note: str = ""

    def attack_pct(self) -> dict[str, float]:
        s = float(self.squad.attack_pct)
        return {t: self.troops[t].attack_pct + s for t in TROOP_TYPES}

    def defense_pct(self) -> dict[str, float]:
        s = float(self.squad.defense_pct)
        return {t: self.troops[t].defense_pct + s for t in TROOP_TYPES}

    def lethality_pct(self) -> dict[str, float]:
        s = float(self.squad.lethality_pct)
        return {t: self.troops[t].lethality_pct + s for t in TROOP_TYPES}

    def health_pct(self) -> dict[str, float]:
        s = float(self.squad.health_pct)
        return {t: self.troops[t].health_pct + s for t in TROOP_TYPES}

    def to_dict(self) -> dict[str, Any]:
        return {
            "note": self.note,
            "squad": self.squad.to_dict(),
            "troops": {t: self.troops[t].to_dict() for t in TROOP_TYPES},
        }

    @classmethod
    def empty(cls, *, note: str = "") -> ResearchBonuses:
        return cls(
            troops={t: TroopResearchRow() for t in TROOP_TYPES},
            squad=TroopResearchRow(),
            note=note,
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> ResearchBonuses:
        if raw is None:
            return cls.empty()
        if not isinstance(raw, Mapping):
            raise TypeError(
                f"ResearchBonuses expects mapping; got {type(raw).__name__}"
            )
        note = str(raw.get("note") or "")
        troop_raw = raw.get("troops")
        if troop_raw is None:
            # Flat shape: {infantry: {attack_pct: …}, …}
            troop_raw = {
                t: raw[t] for t in TROOP_TYPES if t in raw and isinstance(raw[t], Mapping)
            }
        if not isinstance(troop_raw, Mapping):
            raise ValueError("research.troops must be a mapping of troop → stats")
        troops = {
            t: TroopResearchRow.from_dict(troop_raw.get(t)) for t in TROOP_TYPES
        }
        squad = TroopResearchRow.from_dict(
            raw.get("squad") if isinstance(raw.get("squad"), Mapping) else None
        )
        return cls(troops=troops, squad=squad, note=note)


__all__ = ["ResearchBonuses", "TroopResearchRow", "TROOP_TYPES"]
