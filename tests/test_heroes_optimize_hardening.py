"""Hardening: section errors, defense explain, LOO critical, icons."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ks.heroes.models import HeroRecord
from ks.heroes.optimize.arena import load_arena_roles, optimize_arena_defense
from ks.heroes.optimize.explain import leave_one_out_arena
from ks.heroes.optimize.types import CatalogEntry, EffectTag
from ks.heroes.ui.optimize_run import attach_gear_icon_urls, run_optimize_bundle


def _cat(
    name: str,
    troop: str,
    *,
    arena_role: str,
    arena_value: float,
    arena_tags: tuple[str, ...] = (),
) -> CatalogEntry:
    return CatalogEntry(
        name=name,
        troop=troop,
        widget_type="none",
        effects=(EffectTag("attack_up", 10.0, "expedition"),),
        arena_role=arena_role,
        arena_value=arena_value,
        arena_tags=arena_tags,
    )


def _five_catalog() -> dict[str, CatalogEntry]:
    return {
        "Helga": _cat("Helga", "infantry", arena_role="front_fighter", arena_value=90, arena_tags=("tank",)),
        "Howard": _cat("Howard", "infantry", arena_role="front_tank", arena_value=85, arena_tags=("tank",)),
        "Jabel": _cat("Jabel", "cavalry", arena_role="back_cc", arena_value=92, arena_tags=("cc",)),
        "Chenko": _cat("Chenko", "cavalry", arena_role="back_dps", arena_value=88, arena_tags=("dps",)),
        "Saul": _cat("Saul", "archer", arena_role="back_cc", arena_value=80, arena_tags=("cc",)),
    }


def test_run_optimize_bundle_isolates_section_failure() -> None:
    heroes = [
        HeroRecord(name=n, stars=3, power=300_000)
        for n in ("Helga", "Howard", "Jabel", "Chenko", "Saul", "Gordon", "Diana")
    ]
    root = Path(__file__).resolve().parents[1]
    import ks.heroes.ui.optimize_run as mod

    real_bundle = mod._event_bundle
    calls = {"n": 0}

    def selective(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("sword broken")
        return real_bundle(*args, **kwargs)

    with patch.object(mod, "_event_bundle", side_effect=selective):
        bundle = run_optimize_bundle(heroes, config_root=root)

    assert "sword" in bundle["errors"]
    assert bundle["sword"]["status"] == "Error"
    assert bundle["bear"]["modes"]
    assert bundle["arena"]["attack"]["status"] == "Optimal"
    assert bundle["arena"]["defense"]["status"] == "Optimal"


def test_no_section_reads_a_second_troops_file(tmp_path: Path) -> None:
    """`troops_path` must be the *only* troops file the whole bundle opens.

    The bug this guards is one Task 2 already shipped once: a second read of
    the troops config that ignored the parameter, so edited troop counts
    applied to some sections and silently not to others. The merge that
    brought Conquest in re-opened the question for a fourth section, and a
    per-section equality check cannot answer it — a section that wrongly
    reads the repo's config/troops.yaml produces a stable, plausible answer,
    identical across two runs with different overrides. So this asserts on
    the *reads themselves* rather than on the output:

      - the override is genuinely consumed, and
      - `<root>/config/troops.yaml` is never opened at all, by any section.

    Every config loader under run_optimize_bundle goes through
    Path.read_text (load_troops_config, load_catalog, load_scenarios,
    load_event_profile, load_troop_stats, load_combat_roles), so recording
    that one method sees all of them. Conquest currently reads no troops file
    by any name — optimize_conquest scores from the catalog, conquest_roles
    and gear — and this is what keeps that true: wire a load_troops_config
    into it that resolves its own path and the repo file shows up here.
    """
    heroes = [
        HeroRecord(name=n, stars=3, power=300_000)
        for n in ("Helga", "Howard", "Jabel", "Chenko", "Saul", "Gordon", "Diana")
    ]
    root = Path(__file__).resolve().parents[1]
    repo_troops = root / "config" / "troops.yaml"

    override = tmp_path / "troops.yaml"
    override.write_text(repo_troops.read_text(encoding="utf-8"), encoding="utf-8")

    reads: list[Path] = []
    real_read_text = Path.read_text

    def recording(self, *args, **kwargs):
        reads.append(Path(self).resolve())
        return real_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", recording):
        bundle = run_optimize_bundle(heroes, config_root=root, troops_path=override)

    # A section that blew up would take its reads with it and make the
    # "never opened" half vacuous, so pin that all four actually ran.
    assert bundle["errors"] == {}, bundle["errors"]
    assert bundle["conquest"]["status"] == "Optimal"
    assert bundle["arena"]["attack"]["status"] == "Optimal"
    assert bundle["sword"]["modes"] and bundle["bear"]["modes"]

    assert override.resolve() in reads, "the troops_path override was never read"
    assert repo_troops.resolve() not in reads, (
        "a section read the repo's config/troops.yaml instead of the override"
    )


def test_arena_defense_explanations_and_loo_critical() -> None:
    catalog = _five_catalog()
    heroes = [
        HeroRecord(name=n, stars=3, power=p)
        for n, p in [
            ("Helga", 170_000),
            ("Howard", 390_000),
            ("Jabel", 560_000),
            ("Chenko", 330_000),
            ("Saul", 240_000),
        ]
    ]
    roles = load_arena_roles("config/arena_roles.yaml", catalog=catalog)
    result = optimize_arena_defense(heroes, catalog, roles)
    assert result.status == "Optimal"
    assert result.explanations
    for name in result.heroes:
        exp = result.explanations[name]
        assert exp["slot"] in {"F1", "F2", "B1", "B2", "B3"}
        assert exp["fits_because"]
        assert "leave_one_out" in exp

    # Exactly 5 heroes → removing any makes arena Infeasible → critical LOO.
    loo = leave_one_out_arena(
        "defense",
        heroes,
        catalog,
        roles,
        result.formation,
        result.score,
    )
    assert any(v.critical for v in loo.values())
    critical = next(v for v in loo.values() if v.critical)
    assert critical.marginal_score is None
    assert critical.status == "Infeasible"


def test_attach_gear_icon_urls_patches_arena_and_events() -> None:
    bundle = {
        "sword": {
            "modes": {
                "garrison": {
                    "gear_assignment": {
                        "Helga": [{"slot": "helmet", "piece_id": "p1", "name": "H"}]
                    }
                }
            }
        },
        "bear": {"modes": {}},
        "arena": {
            "attack": {
                "gear_assignment": {
                    "Jabel": [{"slot": "boots", "piece_id": "p2", "name": "B"}]
                }
            },
            "defense": {
                "gear_assignment": {
                    "Howard": [{"slot": "chest", "piece_id": "p3", "name": "C"}]
                }
            },
        },
        "conquest": {
            "gear_assignment": {
                "Marlin": [{"slot": "helmet", "piece_id": "p4", "name": "M"}]
            }
        },
    }
    attach_gear_icon_urls(
        bundle,
        {
            "p1": "/icons/a.svg",
            "p2": "/icons/b.svg",
            "p3": "/icons/c.svg",
            "p4": "/icons/d.svg",
        },
    )
    assert (
        bundle["sword"]["modes"]["garrison"]["gear_assignment"]["Helga"][0]["icon_url"]
        == "/icons/a.svg"
    )
    assert bundle["arena"]["attack"]["gear_assignment"]["Jabel"][0]["icon_url"] == "/icons/b.svg"
    assert (
        bundle["arena"]["defense"]["gear_assignment"]["Howard"][0]["icon_url"]
        == "/icons/c.svg"
    )
    assert (
        bundle["conquest"]["gear_assignment"]["Marlin"][0]["icon_url"] == "/icons/d.svg"
    )


def test_optimize_page_cache_control(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.store import HeroStore
    from ks.heroes.ui.app import create_app

    store = HeroStore(tmp_path)
    store.upsert(HeroRecord(name="Helga", stars=2, power=1000, scraped_at="t"))
    client = TestClient(create_app(heroes_dir=tmp_path))
    page = client.get("/optimize")
    assert page.status_code == 200
    assert page.headers.get("cache-control") == "no-store"
    assert b'href="/optimiser/events"' in page.content
    events = client.get("/optimize/events")
    assert events.status_code == 200
    assert events.headers.get("cache-control") == "no-store"
    # The board's client-side rendering (and its esc() helper) is asserted by
    # test_optimiser_events_page_has_esc_helper below; the shell must stay
    # uncached either way.
    assert b"Event lineups" in events.content


# --- restoration tracking ----------------------------------------------------
#
# Task 1 (Apple shell) stubbed /optimiser/events, which forced this assertion
# out of test_optimize_page_cache_control above. It was kept alive as a strict
# xfail against the new route until the page that owes it shipped; Task 6
# shipped it, so the mark is gone and this is an ordinary test again.
#
# Fix wave 1 RE-ANCHORED the needle without changing it. It used to read
# `/optimiser/events`, which forced the board's script to be inline; the
# escaping helper is now shared with hero_detail.js and lives in app.js, so
# the identical `b"function esc("` is asserted against the bytes the app
# serves for /static/app.js instead. The whole chain is pinned here — the
# page loads the board module, the board module loads through the shared
# helper, and the helper is defined once — so nothing is loosened by the
# move. What esc() actually escapes is executed in
# tests/test_heroes_optimiser_events_js.py.
def test_optimiser_events_page_has_esc_helper(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ks.heroes.store import HeroStore
    from ks.heroes.ui.app import create_app

    store = HeroStore(tmp_path)
    store.upsert(HeroRecord(name="Helga", stars=2, power=1000, scraped_at="t"))
    client = TestClient(create_app(heroes_dir=tmp_path))
    events = client.get("/optimiser/events")
    assert events.status_code == 200

    # The page ships the board, the board comes with the shared helpers.
    assert b'src="/static/optimiser_events.js"' in events.content
    assert b'src="/static/app.js"' in events.content
    board = client.get("/static/optimiser_events.js")
    assert board.status_code == 200
    assert b"window.escapeHtml" in board.content

    shared = client.get("/static/app.js")
    assert shared.status_code == 200
    assert b"function esc(" in shared.content
