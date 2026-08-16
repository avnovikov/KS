"""Bear Trap joiner-pool helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from ks.heroes.models import HeroRecord


def _hero(name: str, troop: str) -> HeroRecord:
    return HeroRecord(
        name=name,
        troop_type=troop,
        rarity="legendary",
        stars=5,
        pellets=0,
        power=1_000_000,
        level=50,
    )


def test_filter_heroes_by_allowlist_keeps_order_and_case() -> None:
    from ks.heroes.ui.optimize_run import filter_heroes_by_allowlist

    heroes = [
        _hero("Helga", "infantry"),
        _hero("Saul", "archers"),
        _hero("Chenko", "cavalry"),
    ]
    out = filter_heroes_by_allowlist(heroes, ["chenko", "Helga"])
    assert [h.name for h in out] == ["Helga", "Chenko"]


def test_filter_heroes_by_allowlist_rejects_unknown() -> None:
    from ks.heroes.ui.optimize_run import filter_heroes_by_allowlist

    with pytest.raises(ValueError, match="unknown"):
        filter_heroes_by_allowlist([_hero("Helga", "infantry")], ["Nope"])


def test_filter_heroes_by_allowlist_requires_non_empty() -> None:
    from ks.heroes.ui.optimize_run import filter_heroes_by_allowlist

    with pytest.raises(ValueError, match="empty"):
        filter_heroes_by_allowlist([_hero("Helga", "infantry")], [])


def test_run_beartrap_joiner_excludes_locked_out_heroes(tmp_path: Path) -> None:
    """Joiner allow-list must not pick heroes omitted from the pool."""
    from ks.heroes.ui.optimize_run import run_beartrap_joiner

    # Use a wide roster; lock out a distinctive name and assert absence.
    root = Path(__file__).resolve().parents[1]
    # Prefer real catalog names from fixtures used elsewhere if needed —
    # call with synthetic heroes that match catalog keys when possible.
    from ks.heroes.optimize.catalog import load_catalog

    catalog = load_catalog(None, root / "config" / "hero_catalog.yaml")
    # Pick three distinct troops from catalog for a viable joiner, plus extras.
    by_troop: dict[str, list[str]] = {"infantry": [], "cavalry": [], "archers": [], "archer": []}
    for name, entry in catalog.items():
        troop = (entry.troop or "").lower()
        if troop in by_troop and len(by_troop[troop]) < 3:
            by_troop[troop].append(name)
    # normalize archer -> archers bucket for picks
    archers = by_troop["archers"] or by_troop["archer"]
    infantry = by_troop["infantry"]
    cavalry = by_troop["cavalry"]
    assert infantry and cavalry and archers

    locked = infantry[0]
    pool = [infantry[1], cavalry[0], archers[0], cavalry[1] if len(cavalry) > 1 else cavalry[0]]
    # ensure locked not in pool
    pool = [n for n in pool if n != locked]
    heroes = [
        _hero(n, catalog[n].troop or "infantry")
        for n in ([locked] + pool)
        if n in catalog
    ]
    # Deduplicate by name
    seen: set[str] = set()
    uniq: list[HeroRecord] = []
    for h in heroes:
        if h.name in seen:
            continue
        seen.add(h.name)
        uniq.append(h)

    result = run_beartrap_joiner(
        uniq,
        allow_heroes=pool,
        config_root=root,
        troops_path=root / "config" / "troops.yaml",
    )
    # Mode rows must not use section-level status="ok" — the Event lineups
    # board only draws when status is missing or "Optimal".
    assert result.get("status") in (None, "Optimal")
    names = {h["name"] for h in result["heroes"]}
    assert locked not in names
    assert names <= set(pool)


def test_optimiser_events_page_has_joiner_pool_control(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.store import HeroStore
    from ks.heroes.ui.app import create_app

    heroes_dir = tmp_path / "heroes"
    heroes_dir.mkdir()
    HeroStore(heroes_dir).upsert(_hero("Helga", "infantry"))
    client = TestClient(create_app(heroes_dir=heroes_dir))
    page = client.get("/optimiser/events")
    assert page.status_code == 200
    assert 'id="joiner-pool-btn"' in page.text
    assert 'id="joiner-without-lead-btn"' in page.text
    assert 'id="joiner-pool-dialog"' in page.text
