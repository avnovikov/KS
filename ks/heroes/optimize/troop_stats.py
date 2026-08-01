from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class TroopUnitStats:
    attack: float
    defense: float
    lethality: float
    health: float

    @property
    def offense(self) -> float:
        """Per-troop offensive factor used in community damage formulas."""
        return self.attack * self.lethality

    @property
    def toughness(self) -> float:
        """Per-troop defensive factor (health × defense)."""
        return self.health * self.defense


@dataclass(frozen=True)
class TroopStatsTable:
    source: str
    default_truegold: int
    # type -> tier -> truegold -> stats
    stats: dict[str, dict[int, dict[int, TroopUnitStats]]]

    def get(
        self,
        troop_type: str,
        tier: int,
        *,
        truegold: int | None = None,
    ) -> TroopUnitStats:
        key = troop_type.strip().lower()
        if key == "archer":
            key = "archers"
        tg = self.default_truegold if truegold is None else int(truegold)
        try:
            return self.stats[key][int(tier)][tg]
        except KeyError as exc:
            raise KeyError(
                f"missing troop stats for type={key!r} tier={tier} truegold={tg}"
            ) from exc

    def offense(
        self, troop_type: str, tier: int, *, truegold: int | None = None
    ) -> float:
        return self.get(troop_type, tier, truegold=truegold).offense

    def toughness(
        self, troop_type: str, tier: int, *, truegold: int | None = None
    ) -> float:
        return self.get(troop_type, tier, truegold=truegold).toughness


def load_troop_stats(path: Path | str) -> TroopStatsTable:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("troop_stats.yaml must be a mapping")
    stats_raw = raw.get("stats") or {}
    parsed: dict[str, dict[int, dict[int, TroopUnitStats]]] = {}
    for typ, tiers in stats_raw.items():
        parsed[str(typ)] = {}
        for tier, tgs in tiers.items():
            parsed[str(typ)][int(tier)] = {}
            for tg, vals in tgs.items():
                parsed[str(typ)][int(tier)][int(tg)] = TroopUnitStats(
                    attack=float(vals["attack"]),
                    defense=float(vals["defense"]),
                    lethality=float(vals["lethality"]),
                    health=float(vals["health"]),
                )
    return TroopStatsTable(
        source=str(raw.get("source") or ""),
        default_truegold=int(raw.get("default_truegold", 0)),
        stats=parsed,
    )


def inventory_combat_weights(
    levels_by_type: Mapping[str, Mapping[int, int]],
    table: TroopStatsTable,
    *,
    truegold: int = 0,
    mode: str = "rally_lead",
) -> dict[str, float]:
    """
    Average per-troop combat utility for each type given owned tier mix.
    garrison/joiner-hold leans toughness; attack modes lean offense.
    """
    defensive = mode in {"garrison"}
    out: dict[str, float] = {}
    for typ in ("infantry", "cavalry", "archers"):
        levels = levels_by_type.get(typ) or {}
        total_n = sum(int(c) for c in levels.values())
        if total_n <= 0:
            # Flat inventory fallback: use tier 1 TG0 as unit weight 1.0 scale
            unit = table.get(typ, 1, truegold=truegold)
            out[typ] = unit.toughness if defensive else unit.offense
            continue
        score = 0.0
        for tier, count in levels.items():
            unit = table.get(typ, int(tier), truegold=truegold)
            score += int(count) * (unit.toughness if defensive else unit.offense)
        out[typ] = score / total_n
    # Normalize so weights stay in a similar magnitude to previous formation weights.
    baseline = max(out.values()) or 1.0
    return {k: v / baseline for k, v in out.items()}
