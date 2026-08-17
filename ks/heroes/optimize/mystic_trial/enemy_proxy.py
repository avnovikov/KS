"""Build enemy march proxies from saved Radiant opponent records (pre-MC)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ks.heroes.gear_models import GearRecord, GearStats
from ks.heroes.gear_names import canonical_gear_name
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.gear_assign import SLOTS
from ks.heroes.optimize.gear_stats import expedition_stat_fraction
from ks.heroes.optimize.mystic_trial.proxy import MarchScore, score_march
from ks.heroes.optimize.mystic_trial.ratios import TROOP_TYPES
from ks.heroes.optimize.scoring import normalize_troop
from ks.heroes.optimize.stat_contributions import EXPEDITION, hero_contribution
from ks.heroes.optimize.troop_stats import TroopStatsTable, TroopUnitStats
from ks.heroes.optimize.types import CatalogEntry
from ks.heroes.ui.power import compute_gear_power

# Slot → primary expedition label key used by formula pieces.
_SLOT_LABEL = {
    ("infantry", "helmet"): "Infantry Lethality",
    ("infantry", "boots"): "Infantry Lethality",
    ("infantry", "chest"): "Infantry Health",
    ("infantry", "gloves"): "Infantry Health",
    ("cavalry", "helmet"): "Cavalry Lethality",
    ("cavalry", "boots"): "Cavalry Lethality",
    ("cavalry", "chest"): "Cavalry Health",
    ("cavalry", "gloves"): "Cavalry Health",
    ("archers", "helmet"): "Archer Lethality",
    ("archers", "boots"): "Archer Lethality",
    ("archers", "chest"): "Archer Health",
    ("archers", "gloves"): "Archer Health",
}


def bonus_to_percent_points(raw: float) -> float:
    """Pass battle-report / UI values through as percent-points.

    ``score_march`` applies ``1 + pp/100``. Enter what you mean as the bonus:
    ``115`` → +115% (×2.15), ``33`` → +33% (×1.33). Do **not** rewrite
    game-style totals (``115`` used to become +15); stored opponent YAML and
    player estimates both use the same percent-point convention.
    """
    return float(raw)


def mythic_set_for_troop(troop: str, *, enhancement: int) -> dict[str, GearRecord]:
    """Preset mythic 4-piece set at a shared enhancement level."""
    t = normalize_troop(troop) or "infantry"
    enh = int(enhancement)
    if enh < 0:
        raise ValueError(f"gear enhancement must be >= 0; got {enh}")
    frac = expedition_stat_fraction("mythic", enh, None)
    pct = float(frac or 0.0) * 100.0
    out: dict[str, GearRecord] = {}
    for slot in SLOTS:
        label = _SLOT_LABEL[(t, slot)]
        try:
            power = compute_gear_power("mythic", enh, 0)
        except ValueError:
            power = None
        name = (
            canonical_gear_name(troop=t, slot=slot, rarity="mythic")
            or f"mythic {t} {slot}"
        )
        out[slot] = GearRecord(
            piece_id=f"ai-mythic-{t}-{slot}-{enh}",
            name=name,
            troop_type=t,
            slot=slot,
            rarity="mythic",
            enhancement_level=enh,
            mastery_level=0,
            power=power,
            stats=GearStats(expedition={label: pct}),
        )
    return out


def ai_hero_records(
    names: Sequence[str],
    catalog: Mapping[str, CatalogEntry],
    *,
    hero_level: int,
) -> list[HeroRecord]:
    """Build lightweight HeroRecords for named catalog heroes at a shared level."""
    level = int(hero_level)
    if level < 1:
        raise ValueError(f"hero_level must be >= 1; got {level}")
    heroes: list[HeroRecord] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        if not name:
            continue
        entry = catalog.get(name)
        troop = None
        if entry is not None and entry.troop:
            troop = normalize_troop(entry.troop)
        heroes.append(
            HeroRecord(
                name=name,
                level=level,
                troop_type=troop,
                rarity="legendary",
                stars=5,
                pellets=0,
                power=max(100_000, level * 25_000),
            )
        )
    return heroes


def opponent_complete(march: Mapping[str, Any] | None) -> bool:
    """True when march has 3 heroes, levels, and positive troop mass."""
    if not march:
        return False
    names = [str(n).strip() for n in (march.get("hero_names") or []) if str(n).strip()]
    if len(names) < 3:
        return False
    if march.get("hero_level") is None or march.get("gear_enhancement") is None:
        return False
    counts = march.get("counts") or {}
    total = sum(int(counts.get(t, 0) or 0) for t in TROOP_TYPES)
    return total > 0


def units_for_enemy_levels(
    levels: Mapping[str, int],
    table: TroopStatsTable,
    *,
    truegold: int = 0,
) -> dict[str, TroopUnitStats | None]:
    out: dict[str, TroopUnitStats | None] = {}
    for troop in TROOP_TYPES:
        tier = int(levels.get(troop, 6) or 6)
        try:
            out[troop] = table.get(troop, tier, truegold=truegold)
        except Exception:  # noqa: BLE001 — missing tier → skip that troop
            out[troop] = None
    return out


def bonuses_nonzero(bonuses: Mapping[str, Any] | None) -> bool:
    """True when any troop Atk/Def/Leth/HP battle-report field is set."""
    if not bonuses:
        return False
    keys = ("attack_pct", "defense_pct", "lethality_pct", "health_pct")
    for troop in TROOP_TYPES:
        row = bonuses.get(troop) or {}
        for key in keys:
            if abs(float(row.get(key) or 0.0)) > 1e-12:
                return True
    return False


def report_bonus_percent_maps(
    bonuses: Mapping[str, Any] | None,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    """Battle-report bonuses as full formation percent-point maps (not stacked)."""
    atk = {t: 0.0 for t in TROOP_TYPES}
    defense = {t: 0.0 for t in TROOP_TYPES}
    leth = {t: 0.0 for t in TROOP_TYPES}
    hp = {t: 0.0 for t in TROOP_TYPES}
    raw = bonuses or {}
    for troop in TROOP_TYPES:
        row = raw.get(troop) or {}
        atk[troop] = bonus_to_percent_points(float(row.get("attack_pct") or 0.0))
        defense[troop] = bonus_to_percent_points(float(row.get("defense_pct") or 0.0))
        leth[troop] = bonus_to_percent_points(float(row.get("lethality_pct") or 0.0))
        hp[troop] = bonus_to_percent_points(float(row.get("health_pct") or 0.0))
    return atk, defense, leth, hp


def score_enemy_march(
    march: Mapping[str, Any],
    catalog: Mapping[str, CatalogEntry],
    troop_stats: TroopStatsTable,
    *,
    truegold: int = 0,
) -> MarchScore:
    """Proxy-score one saved opponent march.

    Battle-report Atk/Def/Leth/HP are **formation totals** (same scale as the
    in-game report). When any are set, they alone drive combat % — we do **not**
    also stack synthetic AI hero/gear shares (that double-counted and made foes
    look far stronger than a fair fight). Heroes + mythic gear fill % only when
    report bonuses are all zero.
    """
    if not opponent_complete(march):
        raise ValueError("opponent march incomplete for enemy proxy scoring")
    names = [str(n).strip() for n in march["hero_names"] if str(n).strip()][:3]
    hero_level = int(march["hero_level"])
    gear_enh = int(march["gear_enhancement"])
    heroes = ai_hero_records(names, catalog, hero_level=hero_level)
    if len(heroes) < 3:
        raise ValueError("need 3 resolvable hero names for enemy proxy")

    bonuses = march.get("bonuses") or {}
    if bonuses_nonzero(bonuses):
        atk, defense, leth, hp = report_bonus_percent_maps(bonuses)
    else:
        atk = {t: 0.0 for t in TROOP_TYPES}
        defense = {t: 0.0 for t in TROOP_TYPES}
        leth = {t: 0.0 for t in TROOP_TYPES}
        hp = {t: 0.0 for t in TROOP_TYPES}
        for hero in heroes:
            entry = catalog.get(hero.name)
            troop = normalize_troop(hero.troop_type) if hero.troop_type else None
            if troop is None and entry is not None:
                troop = normalize_troop(entry.troop) if entry.troop else None
            troop = troop or "infantry"
            gear = mythic_set_for_troop(troop, enhancement=gear_enh)
            contrib = hero_contribution(
                hero, entry, family=EXPEDITION, gear_pieces=gear
            )
            prefix = {
                "infantry": "Infantry",
                "cavalry": "Cavalry",
                "archers": "Archer",
            }[troop]
            for suffix, bucket in (
                ("Attack", atk),
                ("Defense", defense),
                ("Lethality", leth),
                ("Health", hp),
            ):
                share = contrib.stats.get(f"{prefix} {suffix}")
                if share is not None:
                    bucket[troop] += float(share.total)

    units = units_for_enemy_levels(march.get("levels") or {}, troop_stats, truegold=truegold)
    return score_march(
        march.get("counts") or {},
        units,
        atk_pct=atk,
        def_pct=defense,
        leth_pct=leth,
        hp_pct=hp,
    )


__all__ = [
    "ai_hero_records",
    "bonus_to_percent_points",
    "bonuses_nonzero",
    "mythic_set_for_troop",
    "opponent_complete",
    "report_bonus_percent_maps",
    "score_enemy_march",
    "units_for_enemy_levels",
]
