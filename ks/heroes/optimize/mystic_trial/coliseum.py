"""Coliseum dual-march mystic-trial optimiser (heroes + gear primary).

Uses the Radiant Spire search pipeline (exclusive dual marches + layered ratio
search) with Coliseum room ratios and ``governor_weight=0`` — heroes/gear
drive the proxy; governor percents stay off unless callers opt in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.mystic_trial.proxy import PROXY_BANNER
from ks.heroes.optimize.troop_stats import TroopStatsTable
from ks.heroes.optimize.types import CatalogEntry, TroopsConfig
from ks.heroes.research_models import ResearchBonuses

_DEFAULT_ROOM = (
    Path(__file__).resolve().parents[4] / "config" / "mystic_trial" / "coliseum.yaml"
)


@dataclass(frozen=True)
class MarchResult:
    hero_names: tuple[str, ...]
    ratio: dict[str, float]
    counts: dict[str, int]
    capacity: int
    score: float
    breakdown: dict[str, Any]
    gear_assignment: dict[str, list[dict[str, Any]]] | None = None
    heroes: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "hero_names": list(self.hero_names),
            "ratio": dict(self.ratio),
            "counts": dict(self.counts),
            "capacity": self.capacity,
            "score": self.score,
            "breakdown": dict(self.breakdown),
        }
        if self.heroes:
            out["heroes"] = [dict(h) for h in self.heroes]
        if self.gear_assignment is not None:
            out["gear_assignment"] = {
                name: [dict(p) for p in pieces]
                for name, pieces in self.gear_assignment.items()
            }
        return out


@dataclass(frozen=True)
class ColiseumResult:
    marches: tuple[MarchResult, ...]
    lineup_score: float
    governor: dict[str, Any]
    room: str = "coliseum"
    proxy_banner: str = PROXY_BANNER
    active_marches: int = 2
    schema_marches: int = 2
    engine: str = "proxy"
    floor: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        marches: list[dict[str, Any] | None] = [m.to_dict() for m in self.marches]
        while len(marches) < self.schema_marches:
            marches.append(None)
        out = {
            "marches": marches,
            "lineup_score": self.lineup_score,
            "governor": dict(self.governor),
            "room": self.room,
            "proxy_banner": self.proxy_banner,
            "active_marches": self.active_marches,
            "schema_marches": self.schema_marches,
            "engine": self.engine,
        }
        if self.floor is not None:
            out["floor"] = dict(self.floor)
        return out


def optimize_coliseum(
    heroes: Sequence[HeroRecord],
    catalog: dict[str, CatalogEntry],
    *,
    gear_pieces: Sequence[GearRecord],
    governor: GovernorTroopBonuses,
    troops: TroopsConfig,
    troop_stats: TroopStatsTable,
    truegold: int | None = None,
    one_per_troop_type: bool = True,
    governor_weight: float = 0.0,
    room_path: Path | str | None = None,
    saved_opponents: Sequence[Mapping[str, Any]] | None = None,
    player_event_troops: Mapping[str, Any] | None = None,
) -> ColiseumResult:
    """Dual-march Coliseum via Radiant search; governor off by default."""
    from ks.heroes.optimize.mystic_trial.rooms import load_room
    from ks.heroes.optimize.radiant_spire import optimize_radiant

    if governor_weight < 0:
        raise ValueError(f"governor_weight must be >= 0; got {governor_weight}")

    path = Path(room_path) if room_path is not None else _DEFAULT_ROOM
    room = load_room(path)
    active = int(room.active_marches or 2)
    schema = int(room.schema_marches or active)

    radiant = optimize_radiant(
        heroes,
        catalog,
        gear_pieces=gear_pieces,
        governor=governor,
        troops=troops,
        troop_stats=troop_stats,
        research=ResearchBonuses.empty(),
        active_marches=active,
        truegold=truegold,
        one_per_troop_type=one_per_troop_type,
        governor_weight=governor_weight,
        room_path=path,
        saved_opponents=saved_opponents,
        player_event_troops=player_event_troops,
    )

    marches = tuple(
        MarchResult(
            hero_names=m.hero_names,
            ratio=dict(m.ratio),
            counts=dict(m.counts),
            capacity=m.capacity,
            score=m.score,
            breakdown=dict(m.breakdown),
            gear_assignment=m.gear_assignment,
            heroes=tuple(m.heroes),
        )
        for m in radiant.marches
    )
    banner = (
        PROXY_BANNER
        + " Heroes + gear primary; governor weight "
        + f"{governor_weight:g}."
    )
    return ColiseumResult(
        marches=marches,
        lineup_score=float(radiant.lineup_score),
        governor=dict(radiant.governor),
        room=room.id,
        proxy_banner=banner,
        active_marches=len(marches),
        schema_marches=schema,
        engine=radiant.engine,
        floor=dict(radiant.floor) if radiant.floor is not None else None,
    )


__all__ = ["ColiseumResult", "MarchResult", "optimize_coliseum"]
