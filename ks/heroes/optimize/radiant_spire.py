"""Radiant Spire dual-march proxy optimiser (foundational score).

Proxy is tunable, not game-authoritative — see design spec.
Floor stubs / MC: mystic_trial floors + combat_mc (GitHub #37 / #38).
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord
from ks.heroes.governor_models import GovernorTroopBonuses
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.bear_damage import blend_unit_stats
from ks.heroes.optimize.gear_assign import assign_best_sets, assignment_to_dict
from ks.heroes.optimize.mystic_trial.floors import FloorStub
from ks.heroes.optimize.mystic_trial.proxy import (
    PROXY_BANNER,
    MarchScore,
    score_march,
)
from ks.heroes.optimize.mystic_trial.ratios import (
    TROOP_TYPES,
    counts_for_ratio,
    normalize_ratio,
    ratio_candidates,
)
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.stat_contributions import (
    EXPEDITION,
    formation_contribution,
    hero_contribution,
)
from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats
from ks.heroes.optimize.types import CatalogEntry, TroopsConfig
from ks.heroes.research_models import ResearchBonuses

# Radiant seed kept for callers / tests that import SEED_RATIO.
SEED_RATIO: dict[str, float] = {
    "infantry": 0.50,
    "cavalry": 0.15,
    "archers": 0.35,
}
PUBLISHED_RATIOS: tuple[dict[str, float], ...] = (
    SEED_RATIO,
    {"infantry": 0.55, "cavalry": 0.10, "archers": 0.35},
    {"infantry": 0.60, "cavalry": 0.10, "archers": 0.30},
    {"infantry": 0.50, "cavalry": 0.10, "archers": 0.40},
    {"infantry": 0.50, "cavalry": 0.20, "archers": 0.30},
    {"infantry": 1 / 3, "cavalry": 1 / 3, "archers": 1 / 3},
)

# Back-compat alias used by older imports.
_normalize_ratio = normalize_ratio


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
class RadiantResult:
    marches: tuple[MarchResult, ...]
    lineup_score: float
    governor: dict[str, Any]
    research: dict[str, Any] | None = None
    proxy_banner: str = PROXY_BANNER
    active_marches: int = 2
    schema_marches: int = 3
    floor: dict[str, Any] | None = None
    opponent: dict[str, Any] | None = None
    engine: str = "proxy"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        marches: list[dict[str, Any] | None] = [m.to_dict() for m in self.marches]
        while len(marches) < self.schema_marches:
            marches.append(None)
        out: dict[str, Any] = {
            "marches": marches,
            "lineup_score": self.lineup_score,
            "governor": dict(self.governor),
            "proxy_banner": self.proxy_banner,
            "active_marches": self.active_marches,
            "schema_marches": self.schema_marches,
            "engine": self.engine,
        }
        if self.research is not None:
            out["research"] = dict(self.research)
        if self.floor is not None:
            out["floor"] = dict(self.floor)
        if self.opponent is not None:
            out["opponent"] = dict(self.opponent)
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out


def build_opponent_panel(
    player_marches: Sequence[MarchResult],
    stub: FloorStub,
) -> dict[str, Any]:
    """Two AI marches with stub ratio/counts and battle-report bonuses (display)."""
    bonuses = {t: dict(stub.enemy_bonuses.get(t, {})) for t in TROOP_TYPES}
    opp_marches: list[dict[str, Any]] = []
    for march in player_marches:
        filled = sum(int(march.counts.get(t, 0)) for t in TROOP_TYPES)
        # Unlimited owned so ratio fills exactly to the mirrored march size.
        owned = {t: filled for t in TROOP_TYPES}
        counts = (
            counts_for_ratio(stub.enemy_ratio, filled, owned)
            if filled > 0
            else {t: 0 for t in TROOP_TYPES}
        )
        opp_marches.append(
            {
                "hero_names": ["AI", "AI", "AI"],
                "hero_level": None,
                "gear_enhancement": None,
                "ratio": dict(stub.enemy_ratio),
                "counts": dict(counts),
                "levels": {t: 6 for t in TROOP_TYPES},
                "capacity": int(march.capacity),
                "bonuses": {t: dict(bonuses[t]) for t in TROOP_TYPES},
            }
        )
    return {
        "marches": opp_marches,
        "bonuses": bonuses,
        "note": (
            "Select an opponent march below, then pick 3 heroes, shared hero "
            "level, gold gear +, troop level/count, and bonuses. Apply saves."
        ),
    }


def _expedition_board_payload(
    pick: Sequence[HeroRecord],
    catalog: Mapping[str, CatalogEntry],
    gear_by_hero: Mapping[str, Mapping[str, GearRecord]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Swordland-shaped contributions for the Radiant march board."""
    contribs: dict[str, Any] = {}
    for hero in pick:
        contribs[hero.name] = hero_contribution(
            hero,
            catalog.get(hero.name),
            family=EXPEDITION,
            gear_pieces=gear_by_hero.get(hero.name),
            catalog=dict(catalog),
        )
    contributions = {name: c.to_dict() for name, c in contribs.items()}
    totals = formation_contribution(list(contribs.values())).to_dict()
    heroes = [
        {"name": h.name, "contributions": contributions.get(h.name)} for h in pick
    ]
    return contributions, totals, heroes


def _hero_troop(hero: HeroRecord, entry: CatalogEntry | None) -> str | None:
    if entry is not None:
        troop = normalize_troop(entry.troop)
        if troop:
            return troop
    return normalize_troop(hero.troop_type)


def _stat_points(contrib_stats: Mapping[str, Any], troop: str, suffix: str) -> float:
    prefix = {
        "infantry": "Infantry",
        "cavalry": "Cavalry",
        "archers": "Archer",
    }[troop]
    share = contrib_stats.get(f"{prefix} {suffix}")
    if share is None:
        return 0.0
    return float(share.total)


def _radiant_rank(contrib: Any, troop: str) -> float:
    """Attack+Lethality primary, Defense+Health secondary."""
    atk = _stat_points(contrib.stats, troop, "Attack")
    leth = _stat_points(contrib.stats, troop, "Lethality")
    defense = _stat_points(contrib.stats, troop, "Defense")
    hp = _stat_points(contrib.stats, troop, "Health")
    power = float(contrib.power.total)
    return 4.0 * atk + 3.0 * leth + 1.5 * defense + 1.5 * hp + power / 1_000_000.0


def _inventory_levels(troops: TroopsConfig) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = {}
    for typ in TROOP_TYPES:
        levels = troops.levels(typ)
        if levels:
            out[typ] = dict(levels)
        else:
            owned = troops.owned(typ)
            out[typ] = {6: owned} if owned > 0 else {}
    return out


def _blend_units(
    levels: Mapping[str, Mapping[int, int]],
    table: TroopStatsTable,
    *,
    truegold: int,
) -> dict[str, TroopUnitStats | None]:
    return {
        typ: blend_unit_stats(levels.get(typ) or {}, table, typ, truegold=truegold)
        for typ in TROOP_TYPES
    }


def _pick_march_heroes(
    pool: list[tuple[HeroRecord, str, float]],
    *,
    one_per_troop_type: bool = True,
) -> list[HeroRecord]:
    """Greedy: take best remaining hero per troop type (or top 3)."""
    if not one_per_troop_type:
        return [h for h, _t, _r in sorted(pool, key=lambda row: row[2], reverse=True)[:3]]
    chosen: list[HeroRecord] = []
    used_troops: set[str] = set()
    for hero, troop, _rank in sorted(pool, key=lambda row: row[2], reverse=True):
        if troop in used_troops:
            continue
        chosen.append(hero)
        used_troops.add(troop)
        if len(chosen) == 3:
            break
    return chosen


def _lineup_troop_percents(
    heroes: Sequence[HeroRecord],
    catalog: Mapping[str, CatalogEntry],
    gear_by_hero: Mapping[str, Mapping[str, GearRecord]],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], dict[str, Any]]:
    atk = {t: 0.0 for t in TROOP_TYPES}
    defense = {t: 0.0 for t in TROOP_TYPES}
    leth = {t: 0.0 for t in TROOP_TYPES}
    hp = {t: 0.0 for t in TROOP_TYPES}
    shares: dict[str, Any] = {"heroes": {}}
    for hero in heroes:
        entry = catalog.get(hero.name)
        troop = _hero_troop(hero, entry) or "infantry"
        contrib = hero_contribution(
            hero,
            entry,
            family=EXPEDITION,
            gear_pieces=gear_by_hero.get(hero.name),
        )
        atk[troop] += _stat_points(contrib.stats, troop, "Attack")
        defense[troop] += _stat_points(contrib.stats, troop, "Defense")
        leth[troop] += _stat_points(contrib.stats, troop, "Lethality")
        hp[troop] += _stat_points(contrib.stats, troop, "Health")
        shares["heroes"][hero.name] = {
            "troop": troop,
            "attack": _stat_points(contrib.stats, troop, "Attack"),
            "defense": _stat_points(contrib.stats, troop, "Defense"),
            "lethality": _stat_points(contrib.stats, troop, "Lethality"),
            "health": _stat_points(contrib.stats, troop, "Health"),
            "rank": _radiant_rank(contrib, troop),
        }
    return atk, defense, leth, hp, shares


def _stub_enemy_march_score(
    stub: FloorStub,
    *,
    capacity: int,
    units: Mapping[str, TroopUnitStats | None],
) -> MarchScore:
    """Fixed enemy march from floor ratio/bonuses × power scale (no saved foe)."""
    from ks.heroes.optimize.mystic_trial.enemy_proxy import bonus_to_percent_points

    cap = max(0, int(capacity))
    owned = {t: cap for t in TROOP_TYPES}
    counts = counts_for_ratio(stub.enemy_ratio, cap, owned)
    atk: dict[str, float] = {}
    defense: dict[str, float] = {}
    leth: dict[str, float] = {}
    hp: dict[str, float] = {}
    for troop in TROOP_TYPES:
        row = stub.enemy_bonuses.get(troop) or {}
        atk[troop] = bonus_to_percent_points(float(row.get("attack_pct") or 0.0))
        defense[troop] = bonus_to_percent_points(float(row.get("defense_pct") or 0.0))
        leth[troop] = bonus_to_percent_points(float(row.get("lethality_pct") or 0.0))
        hp[troop] = bonus_to_percent_points(float(row.get("health_pct") or 0.0))
    base = score_march(
        counts, units, atk_pct=atk, def_pct=defense, leth_pct=leth, hp_pct=hp
    )
    scale = max(0.0, float(stub.enemy_power_scale))
    by_type = {
        t: {
            "n": float((base.by_type.get(t) or {}).get("n") or 0.0),
            "offense": float((base.by_type.get(t) or {}).get("offense") or 0.0) * scale,
            "tough": float((base.by_type.get(t) or {}).get("tough") or 0.0) * scale,
        }
        for t in TROOP_TYPES
    }
    return MarchScore(
        score=float(base.score) * scale,
        offense_sum=float(base.offense_sum) * scale,
        tough_sum=float(base.tough_sum) * scale,
        by_type=by_type,
    )


def optimize_radiant(
    heroes: Sequence[HeroRecord],
    catalog: Mapping[str, CatalogEntry],
    *,
    gear_pieces: Sequence[GearRecord],
    governor: GovernorTroopBonuses,
    troops: TroopsConfig,
    troop_stats: TroopStatsTable,
    research: ResearchBonuses | None = None,
    active_marches: int = 2,
    truegold: int | None = None,
    one_per_troop_type: bool = True,
    governor_weight: float = 1.0,
    floor: int | None = None,
    floors_path: Path | str | None = None,
    room_path: Path | str | None = None,
    event_march_capacity: int | None | types.EllipsisType = ...,
    event_troop_tier: int | None | types.EllipsisType = ...,
    player_event_troops: Mapping[str, Any] | None = None,
    enemy_ratio: Mapping[str, float] | None = None,
    enemy_bonuses: Mapping[str, Mapping[str, float]] | None = None,
    saved_opponents: Sequence[Mapping[str, Any]] | None = None,
    player_report_bonuses: Mapping[str, Mapping[str, float]] | None = None,
) -> RadiantResult:
    """Assign exclusive hero marches and search troop ratios via proxy score.

    ``event_march_capacity`` / ``event_troop_tier``: omit to use room YAML;
    pass explicit values to override; pass ``None`` for capacity to force
    inventory march capacity (+ escorts).

    ``player_event_troops`` ``{tier, march_size}`` overrides both when set
    (stage·round event-borrowed troops — not inventory mix).
    """
    from pathlib import Path as _Path

    from ks.heroes.optimize.mystic_trial.floors import get_floor, load_floors
    from ks.heroes.optimize.mystic_trial.radiant_opponents import (
        parse_player_event_troops,
    )
    from ks.heroes.optimize.mystic_trial.rooms import load_room

    if active_marches not in (1, 2, 3):
        raise ValueError(f"active_marches must be 1–3; got {active_marches}")
    if governor_weight < 0:
        raise ValueError(f"governor_weight must be >= 0; got {governor_weight}")
    if (enemy_ratio is not None or enemy_bonuses is not None) and floor is None:
        raise ValueError("enemy_ratio / enemy_bonuses overrides require floor=")

    gov_w = float(governor_weight)
    research_bonuses = research if research is not None else ResearchBonuses.empty()
    research_atk = research_bonuses.attack_pct()
    research_def = research_bonuses.defense_pct()
    research_leth = research_bonuses.lethality_pct()
    research_hp = research_bonuses.health_pct()

    published = PUBLISHED_RATIOS
    room_event_cap: int | None = None
    room_event_tier: int | None = None
    room_file = (
        _Path(room_path)
        if room_path is not None
        else _Path(__file__).resolve().parents[3]
        / "config"
        / "mystic_trial"
        / "radiant_spire.yaml"
    )
    if room_file.is_file():
        room = load_room(room_file)
        published = room.published_ratios
        room_event_cap = room.event_march_capacity
        room_event_tier = room.event_troop_tier
    event_cap: int | None
    event_tier: int | None
    pet: dict[str, int] | None = None
    if player_event_troops is not None:
        pet = parse_player_event_troops(player_event_troops)
        event_cap = pet["march_size"]
        event_tier = pet["tier"]
    elif event_march_capacity is None:
        # Explicit None → inventory march capacity (+ escorts), ignore room event troops.
        event_cap = None
        event_tier = None
    else:
        if event_march_capacity is ...:
            event_cap = room_event_cap
        else:
            event_cap = event_march_capacity
        if event_troop_tier is ...:
            event_tier = room_event_tier
        else:
            event_tier = event_troop_tier
        if event_tier is not None and event_cap is None:
            from ks.heroes.optimize.mystic_trial.radiant_opponents import (
                DEFAULT_EVENT_MARCH_SIZE,
            )

            event_cap = DEFAULT_EVENT_MARCH_SIZE
        elif event_cap is not None and event_tier is None:
            from ks.heroes.optimize.mystic_trial.radiant_opponents import (
                DEFAULT_EVENT_TROOP_TIER,
            )

            event_tier = DEFAULT_EVENT_TROOP_TIER

    warnings: list[str] = []
    floor_payload: dict[str, Any] | None = None
    floor_stub = None
    if floor is not None:
        path = (
            _Path(floors_path)
            if floors_path is not None
            else _Path(__file__).resolve().parents[3]
            / "config"
            / "mystic_trial"
            / "radiant_spire_floors.yaml"
        )
        stubs = load_floors(path)
        floor_stub = get_floor(stubs, int(floor))
        if floor_stub is None:
            warnings.append(
                f"unknown Radiant floor {floor}; using proxy without floor stub"
            )
        else:
            if enemy_ratio is not None or enemy_bonuses is not None:
                floor_stub = floor_stub.with_overrides(
                    enemy_ratio=enemy_ratio,
                    enemy_bonuses=enemy_bonuses,
                )
            floor_payload = floor_stub.to_dict()
            if enemy_ratio is not None or enemy_bonuses is not None:
                floor_payload["overrides_applied"] = True
            if event_cap is not None:
                floor_payload["event_march_capacity"] = int(event_cap)
            if event_tier is not None:
                floor_payload["event_troop_tier"] = int(event_tier)

    tg = troop_stats.default_truegold if truegold is None else int(truegold)
    if event_tier is not None and event_cap is not None:
        levels = {t: {int(event_tier): int(event_cap)} for t in TROOP_TYPES}
        owned = {t: int(event_cap) for t in TROOP_TYPES}
    else:
        levels = _inventory_levels(troops)
        owned = {t: troops.owned(t) for t in TROOP_TYPES}
    units = _blend_units(levels, troop_stats, truegold=tg)

    ranked: list[tuple[HeroRecord, str, float]] = []
    for hero in heroes:
        if hero.name not in catalog:
            continue
        entry = catalog[hero.name]
        troop = _hero_troop(hero, entry)
        if troop is None:
            continue
        # Provisional rank without exclusive gear (gear assigned after lineup pick).
        contrib = hero_contribution(hero, entry, family=EXPEDITION, gear_pieces=None)
        ranked.append((hero, troop, _radiant_rank(contrib, troop)))
    ranked.sort(key=lambda row: row[2], reverse=True)

    remaining = list(ranked)
    marches: list[MarchResult] = []
    remaining_owned = dict(owned)
    saved_list = list(saved_opponents or ())

    from ks.heroes.optimize.mystic_trial.enemy_proxy import (
        opponent_complete,
        score_enemy_march,
    )

    enemy_scores: list[Any] = []
    for i, saved in enumerate(saved_list[:active_marches]):
        # Saved battle-report marches score as enemies even without a floor stub
        # (Coliseum stage·round opponents; Radiant when floor unknown).
        if opponent_complete(saved):
            try:
                enemy_scores.append(
                    score_enemy_march(
                        saved, catalog, troop_stats, truegold=tg
                    )
                )
            except (ValueError, KeyError, TypeError) as exc:
                warnings.append(f"opponent march {i + 1}: {exc}")
                enemy_scores.append(None)
        else:
            enemy_scores.append(None)
    if any(enemy_scores):
        if floor_stub is not None:
            floor_payload = dict(floor_payload or floor_stub.to_dict())
        else:
            floor_payload = dict(floor_payload or {})
        floor_payload["enemy_proxy"] = True
    if event_cap is not None or event_tier is not None:
        floor_payload = dict(floor_payload or {})
        if event_cap is not None:
            floor_payload["event_march_capacity"] = int(event_cap)
        if event_tier is not None:
            floor_payload["event_troop_tier"] = int(event_tier)
        if pet is not None:
            floor_payload["player_event_troops"] = dict(pet)

    for march_idx in range(active_marches):
        pick = _pick_march_heroes(remaining, one_per_troop_type=one_per_troop_type)
        if len(pick) < 3:
            break
        pick_names = [h.name for h in pick]
        remaining = [(h, t, r) for h, t, r in remaining if h.name not in pick_names]

        # Marches use fungible class sets (same faceplate may appear on both
        # Coliseum/Radiant marches). Arena is the exclusive-piece path.
        gear_by_hero = assign_best_sets(
            list(heroes),
            dict(catalog),
            list(gear_pieces),
            selected=pick_names,
            profile="early_game_growth",
        )
        gear_assignment = assignment_to_dict(gear_by_hero)
        hero_atk, hero_def, hero_leth, hero_hp, hero_shares = _lineup_troop_percents(
            pick, catalog, gear_by_hero
        )
        leth_pct = {
            t: hero_leth[t] + float(research_leth.get(t, 0.0)) for t in TROOP_TYPES
        }
        hp_pct = {t: hero_hp[t] + float(research_hp.get(t, 0.0)) for t in TROOP_TYPES}
        atk_pct = {
            t: hero_atk[t]
            + gov_w
            * (
                float(governor.attack_pct.get(t, 0.0))
                + float(governor.set_attack_pct)
            )
            + float(research_atk.get(t, 0.0))
            for t in TROOP_TYPES
        }
        def_pct = {
            t: hero_def[t]
            + gov_w
            * (
                float(governor.defense_pct.get(t, 0.0))
                + float(governor.set_defense_pct)
            )
            + float(research_def.get(t, 0.0))
            for t in TROOP_TYPES
        }
        report_bonuses_applied = False
        from ks.heroes.optimize.mystic_trial.enemy_proxy import (
            bonuses_nonzero,
            report_bonus_percent_maps,
        )

        if bonuses_nonzero(player_report_bonuses):
            # Battle-report formation totals replace heroes+governor+research
            # (same rule as opponent scoring — do not stack inventory on top).
            atk_pct, def_pct, leth_pct, hp_pct = report_bonus_percent_maps(
                player_report_bonuses
            )
            report_bonuses_applied = True

        if event_cap is not None:
            # Event troop capacity: each march fills independently for chance calc.
            capacity = int(event_cap)
            fill_cap = capacity
            fill_owned = {t: capacity for t in TROOP_TYPES}
        else:
            escorts = sum(int(h.escorts or 0) for h in pick)
            capacity = troops.march_capacity + escorts
            fill_cap = min(capacity, sum(remaining_owned.values()))
            fill_owned = remaining_owned

        lineup_troops: set[str] = set()
        for hero in pick:
            troop = _hero_troop(hero, catalog.get(hero.name))
            if troop:
                lineup_troops.add(troop)

        from ks.heroes.optimize.mystic_trial.fight_utility import evaluate_attrition
        from ks.heroes.optimize.mystic_trial.radiant_search import search_best_ratio

        saved_enemy = (
            enemy_scores[march_idx] if march_idx < len(enemy_scores) else None
        )
        enemy: MarchScore | None = saved_enemy
        if enemy is None and floor_stub is not None:
            enemy = _stub_enemy_march_score(
                floor_stub,
                capacity=fill_cap,
                units=units,
            )

        mc_trials = 32
        mc_rounds = 10
        mc_seed = (int(floor_stub.floor) * 100 + march_idx) if floor_stub else march_idx

        def _evaluate(player: MarchScore) -> float:
            if enemy is not None:
                util = evaluate_attrition(
                    player,
                    enemy,
                    trials=mc_trials,
                    rounds=mc_rounds,
                    seed=mc_seed,
                )
                # Lexicographic: win rate, then remaining HP, then proxy strength.
                return (
                    float(util.win_rate)
                    + 1e-3 * float(util.remaining_hp_est)
                    + 1e-15 * float(player.score)
                )
            return float(player.score)

        found = search_best_ratio(
            capacity=fill_cap,
            owned=fill_owned,
            units=units,
            atk_pct=atk_pct,
            def_pct=def_pct,
            leth_pct=leth_pct,
            hp_pct=hp_pct,
            lineup_troops=lineup_troops,
            published=published,
            step=0.05,
            min_share=0.05,
            evaluate=_evaluate,
        )
        scored = found["proxy"]
        contributions, formation_totals, hero_rows = _expedition_board_payload(
            pick, catalog, gear_by_hero
        )
        breakdown: dict[str, Any] = {
            "proxy": scored.to_dict(),
            "atk_pct": dict(atk_pct),
            "def_pct": dict(def_pct),
            "leth_pct": dict(leth_pct),
            "hp_pct": dict(hp_pct),
            "hero_shares": hero_shares,
            "governor_attack_pct": dict(governor.attack_pct),
            "governor_defense_pct": dict(governor.defense_pct),
            "set_attack_pct": governor.set_attack_pct,
            "set_defense_pct": governor.set_defense_pct,
            "research": research_bonuses.to_dict(),
            "search": {"min_share": 0.05, "step": 0.05},
            "stat_family": "expedition",
            "contributions": contributions,
            "formation_totals": formation_totals,
        }
        if report_bonuses_applied:
            breakdown["player_report_bonuses"] = True
        if event_cap is not None:
            breakdown["event_march_capacity"] = capacity
        if enemy is not None:
            util = evaluate_attrition(
                scored,
                enemy,
                trials=mc_trials,
                rounds=mc_rounds,
                seed=mc_seed,
            )
            breakdown["mc"] = util.to_dict()
            if saved_enemy is not None:
                breakdown["enemy_proxy"] = True
            rank_key = util.win_rate
        else:
            rank_key = float(scored.score)
        best = MarchResult(
            hero_names=tuple(h.name for h in pick),
            ratio=dict(found["ratio"]),
            counts=dict(found["counts"]),
            capacity=capacity,
            score=rank_key if enemy is not None else scored.score,
            breakdown=breakdown,
            gear_assignment=gear_assignment,
            heroes=tuple(hero_rows),
        )
        if event_cap is None:
            for t in TROOP_TYPES:
                remaining_owned[t] = max(0, remaining_owned[t] - best.counts[t])
        marches.append(best)

    engine = "mc" if (floor_stub is not None or any(enemy_scores)) else "proxy"
    opponent = (
        build_opponent_panel(marches, floor_stub) if floor_stub is not None else None
    )
    return RadiantResult(
        marches=tuple(marches),
        lineup_score=sum(m.score for m in marches),
        governor=governor.to_dict(),
        research=research_bonuses.to_dict(),
        active_marches=active_marches,
        floor=floor_payload,
        opponent=opponent,
        engine=engine,
        warnings=tuple(warnings),
    )


__all__ = [
    "PROXY_BANNER",
    "PUBLISHED_RATIOS",
    "SEED_RATIO",
    "TROOP_TYPES",
    "MarchResult",
    "MarchScore",
    "RadiantResult",
    "build_opponent_panel",
    "counts_for_ratio",
    "optimize_radiant",
    "ratio_candidates",
    "score_march",
]
