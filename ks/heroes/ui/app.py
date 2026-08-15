"""FastAPI app: gear + heroes roster + optimize via stores."""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import yaml

from ks.heroes.assurance import set_field
from ks.heroes.config import DEFAULT_HEROES_CONFIG
from ks.heroes.gear_config import DEFAULT_GEAR_CONFIG
from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_store import GearStore
from ks.heroes.models import HeroRecord
from ks.heroes.optimize.troops import troops_config_from_dict
from ks.heroes.store import HeroStore
from ks.heroes.ui.hero_icons import ensure_all_hero_icons
from ks.heroes.ui.hero_power import scale_power_for_star_change
from ks.heroes.ui.heroes_rescan import rescan_heroes_from_ocr
from ks.heroes.ui.icons import ensure_all_icons
from ks.heroes.ui.power import compute_gear_power
from ks.heroes.ui.rescan import rescan_gear_from_ocr
from ks.heroes.ui.troop_store import TroopStore
from ks.heroes.ui.troops_form import troops_form_model
from ks.heroes.ui.trust import (
    flag_gear_rows,
    flag_hero_rows,
    gear_mastery_required,
    gear_row_incomplete,
    hero_row_incomplete,
    summarize_flags,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STARS_RANGE = range(0, 6)
_PELLETS_RANGE = range(0, 6)
_HERO_LEVEL_RANGE = range(1, 81)
_POWER_MIN = 0
_POWER_MAX = 99_999_999

#: What a hand-edited tuning YAML can throw on the way into a *page*.
#: Deliberately wider than the parse error: a document that loads as a list
#: instead of a mapping reaches `.get` (AttributeError), and a value that is
#: not a number reaches `int()` (ValueError/TypeError). Every one of these is
#: a file the user is expected to edit by hand, and none of them should be
#: able to 500 the screen they would go to in order to notice the mistake.
TUNING_ERRORS = (
    OSError,
    AttributeError,
    KeyError,
    TypeError,
    ValueError,
    yaml.YAMLError,
)


def startup_paths(*, gear: bool, heroes: bool) -> list[tuple[str, str]]:
    """(label, path) for each screen `run_ui` advertises on the console.

    Data rather than a run of print statements so the tests can check every
    path against the app's own routes. The console was the last surface still
    naming the pre-/inventory IA (`/heroes`, `/optimize`, …); those paths do
    still redirect, which is exactly why nothing else caught it.

    Hero levels is reachable in the subnav but not listed here: it is a
    reserved placeholder, and the console is a list of things to go and do.
    """
    rows: list[tuple[str, str]] = []
    if gear:
        rows.append(("Inventory · Gear", "/inventory/gear"))
    if heroes:
        rows.append(("Inventory · Heroes", "/inventory/heroes"))
    # Troops is editable whichever inventory is configured — the optimisers
    # read it either way.
    rows.append(("Inventory · Troops", "/inventory/troops"))
    rows.append(("Inventory · Governor", "/inventory/governor-gear"))
    rows.append(("Inventory · Research", "/inventory/research"))
    if heroes:
        rows.append(("Optimiser · Event lineups", "/optimiser/events"))
        rows.append(("Optimiser · Gear XP", "/optimiser/gear-xp"))
        rows.append(
            (
                "Optimiser · Mystic Trial",
                "/optimiser/events/mystic-trial/radiant-spire",
            )
        )
    return rows


def _troop_totals(raw: dict[str, Any]) -> dict[str, int]:
    """Type/march-capacity totals for the troops API — computed via the same
    validator save_raw() uses, so totals and validation never disagree.
    """
    cfg = troops_config_from_dict(raw)
    return {
        "march_capacity": cfg.march_capacity,
        "infantry": cfg.infantry,
        "cavalry": cfg.cavalry,
        "archers": cfg.archers,
    }


def inventory_revision(dir_path: Path, filename: str) -> str:
    """Stable cache-bust token from inventory JSON mtime."""
    path = dir_path / filename
    if not path.is_file():
        return "0"
    return str(path.stat().st_mtime_ns)


def with_cache_bust(url: str | None, bust: str) -> str | None:
    """Append ?v=… so browsers do not keep stale icons after rescan."""
    if not url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={bust}"


try:
    from fastapi import Body, FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError:  # pragma: no cover - exercised when ui extras missing
    Body = None  # type: ignore[assignment,misc]
    FastAPI = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    HTMLResponse = None  # type: ignore[assignment,misc]
    RedirectResponse = None  # type: ignore[assignment,misc]
    StreamingResponse = None  # type: ignore[assignment,misc]
    StaticFiles = None  # type: ignore[assignment,misc]
    Jinja2Templates = None  # type: ignore[assignment,misc]


def _safe_under(root: Path, relative: str) -> Path | None:
    """Return the resolved path only when it sits inside *root*.

    Returns ``None`` when the candidate would escape the allowed root (e.g.
    via ``../`` segments) or when it refers to something that is not a regular
    file.  Used by every dynamic icon route to prevent cross-user traversal.
    """
    try:
        candidate = (root / relative).resolve()
    except (ValueError, OSError):
        return None
    if not candidate.is_relative_to(root.resolve()):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _resolve_gear_dir(gear: Path) -> Path:
    path = gear.expanduser().resolve()
    if path.is_file() and path.name == "gear.json":
        return path.parent
    if path.is_dir():
        return path
    raise FileNotFoundError(f"gear path not found: {gear}")


def _resolve_heroes_dir(heroes: Path) -> Path:
    path = heroes.expanduser().resolve()
    if path.is_file() and path.name == "heroes.json":
        return path.parent
    if path.is_dir():
        return path
    raise FileNotFoundError(f"heroes path not found: {heroes}")


def sync_piece_power(piece: GearRecord) -> GearRecord:
    """Return piece with power derived from rarity/enhancement/mastery.

    Requires both rarity and enhancement so we never overwrite OCR power with a
    guessed blue/+0 estimate for partial records.
    """
    if piece.enhancement_level is None or not piece.rarity:
        return piece
    from ks.heroes.ui.power import known_rarity

    if not known_rarity(piece.rarity):
        return piece
    power = compute_gear_power(
        piece.rarity, piece.enhancement_level, piece.mastery_level
    )
    if piece.power == power:
        return piece
    return replace(piece, power=power)


_CANONICAL_RARITIES = frozenset(
    {"grey", "green", "blue", "epic", "mythic", "red"}
)
_RARITY_ALIASES = {
    "gray": "grey",
    "common": "grey",
    "white": "grey",
    "uncommon": "green",
    "rare": "blue",
    "purple": "epic",
    "gold": "mythic",
}
_CANONICAL_SLOTS = frozenset({"helmet", "chest", "gloves", "boots"})
_SLOT_ALIASES = {
    "helm": "helmet",
    "hat": "helmet",
    "head": "helmet",
    "armor": "chest",
    "shroud": "chest",
    "gauntlet": "gloves",
    "gauntlets": "gloves",
    "bracers": "gloves",
    "greaves": "boots",
}


#: The vocabularies the gear pickers offer, in game order rather than
#: alphabetical. Kept beside the frozensets `normalize_ui_rarity` /
#: `normalize_ui_slot` validate against, and pinned equal to them by
#: `test_the_gear_pickers_offer_exactly_the_vocabulary_the_api_accepts` — a
#: picker must never offer a value the PATCH it feeds would reject with a 400.
UI_RARITY_CHOICES: tuple[str, ...] = ("grey", "green", "blue", "epic", "mythic", "red")
UI_SLOT_CHOICES: tuple[str, ...] = ("helmet", "chest", "gloves", "boots")
UI_TROOP_CHOICES: tuple[str, ...] = ("infantry", "cavalry", "archers")


def ui_select_value(
    raw: str | None, normalizer: Callable[[str | None], str | None]
) -> str | None:
    """What a gear picker should show for the rarity/slot currently stored.

    Three outcomes, and the third is the load-bearing one:

    - ``""`` — nothing is stored. The picker sits on its "—" option, which is
      also the release control: choosing it clears the field, and a cleared
      field is one the next OCR rescan is allowed to fill in again.
    - the canonical spelling — the stored value is one the PATCH endpoint
      accepts, with aliases folded (``purple`` → ``epic``, ``helm`` →
      ``helmet``).
    - ``None`` — it is neither, i.e. a value hand-edited into ``gear.json``
      that this vocabulary cannot represent. The page renders that cell
      read-only instead of offering a picker, because every save sends the
      row's *whole* editable state: a picker showing "—" over a stored
      ``chartreuse`` would quietly clear it the first time any other box on
      that row was touched.
    """
    if raw is None or str(raw).strip() == "":
        return ""
    try:
        return normalizer(raw)
    except ValueError:
        return None


def normalize_ui_rarity(rarity: str | None) -> str | None:
    """Map UI/OCR rarity labels to a canonical store value."""
    if rarity is None:
        return None
    key = str(rarity).strip().lower()
    if not key:
        return None
    key = _RARITY_ALIASES.get(key, key)
    if key not in _CANONICAL_RARITIES:
        raise ValueError(
            f"rarity must be one of {sorted(_CANONICAL_RARITIES)}; got {rarity!r}"
        )
    return key


def normalize_ui_slot(slot: str | None) -> str | None:
    """Map UI/OCR slot labels to a canonical store value."""
    if slot is None:
        return None
    key = str(slot).strip().lower()
    if not key:
        return None
    key = _SLOT_ALIASES.get(key, key)
    if key not in _CANONICAL_SLOTS:
        raise ValueError(
            f"slot must be one of {sorted(_CANONICAL_SLOTS)}; got {slot!r}"
        )
    return key


def normalize_ui_troop(troop: str | None) -> str | None:
    """Map UI troop labels to inventory store values (infantry/cavalry/archers)."""
    if troop is None:
        return None
    from ks.heroes.gear_names import normalize_troop

    key = normalize_troop(str(troop).strip())
    if key is None or key not in UI_TROOP_CHOICES:
        raise ValueError(
            f"troop_type must be one of {list(UI_TROOP_CHOICES)}; got {troop!r}"
        )
    return key


def next_manual_piece_id(existing_ids: list[str] | tuple[str, ...] | set[str]) -> str:
    """Allocate ``manual-{n}`` with n = 1 + max existing manual index."""
    best = 0
    for raw in existing_ids:
        text = str(raw)
        if not text.startswith("manual-"):
            continue
        suffix = text[len("manual-") :]
        if not suffix.isdigit():
            continue
        best = max(best, int(suffix))
    return f"manual-{best + 1}"


def create_manual_piece(
    store: GearStore,
    *,
    troop_type: str,
    slot: str,
    rarity: str,
) -> GearRecord:
    """Create a new inventory piece; name from ``gear_names.yaml``; persist SQL+JSON."""
    from ks.heroes.gear_names import canonical_gear_name

    troop = normalize_ui_troop(troop_type)
    slot_n = normalize_ui_slot(slot)
    rarity_n = normalize_ui_rarity(rarity)
    if troop is None or slot_n is None or rarity_n is None:
        raise ValueError("troop_type, slot, and rarity are required")
    name = canonical_gear_name(troop=troop, slot=slot_n, rarity=rarity_n)
    if not name:
        raise ValueError(
            f"unknown gear name for troop={troop!r} slot={slot_n!r} rarity={rarity_n!r}"
        )
    piece_id = next_manual_piece_id([p.piece_id for p in store.all_pieces()])
    record = GearRecord(
        piece_id=piece_id,
        name=name,
        troop_type=troop,
        slot=slot_n,
        rarity=rarity_n,
        enhancement_level=None,
        mastery_level=None,
        power=None,
    )
    return store.upsert(record)


def resolve_catalog_hero_name(name: str) -> str:
    """Return canonical catalog hero name (case-insensitive); raise if unknown."""
    from ks.heroes.name_ocr import load_name_catalog

    raw = (name or "").strip()
    if not raw:
        raise ValueError("name is required")
    catalog = load_name_catalog()
    for key in catalog:
        if key.lower() == raw.lower():
            return key
    raise ValueError(f"unknown hero in catalog: {raw!r}")


def catalog_heroes_available_to_add(store: HeroStore) -> list[dict[str, str]]:
    """Catalog entries not already in the roster, sorted by name."""
    from ks.heroes.name_ocr import load_name_catalog

    owned = {h.name.lower() for h in store.all_heroes()}
    rows: list[dict[str, str]] = []
    for key, entry in sorted(load_name_catalog().items(), key=lambda kv: kv[0].lower()):
        if key.lower() in owned:
            continue
        rows.append(
            {
                "name": key,
                "troop": str(entry.troop or ""),
                "rarity": str(entry.rarity or ""),
            }
        )
    return rows


def create_manual_hero(store: HeroStore, *, name: str) -> HeroRecord:
    """Add a catalog hero to the roster; levels/power left empty for manual edit."""
    from ks.heroes.name_ocr import load_name_catalog

    key = resolve_catalog_hero_name(name)
    if any(h.name.lower() == key.lower() for h in store.all_heroes()):
        raise ValueError(f"hero already in roster: {key}")
    entry = load_name_catalog()[key]
    existing = store.all_heroes()
    next_index = max((h.roster_index for h in existing), default=-1) + 1
    record = HeroRecord(
        name=key,
        troop_type=entry.troop,
        rarity=entry.rarity,
        roster_page=0,
        roster_index=next_index,
    )
    return store.upsert(record)


def update_piece_levels(
    store: GearStore,
    piece_id: str,
    *,
    enhancement_level: int | None | object = ...,
    mastery_level: int | None | object = ...,
    rarity: str | None | object = ...,
    slot: str | None | object = ...,
) -> GearRecord:
    """Update enhancement/mastery/rarity/slot; recompute power; persist JSON + DB."""
    pieces = {p.piece_id: p for p in store.all_pieces()}
    piece = pieces.get(piece_id)
    if piece is None:
        raise KeyError(piece_id)

    updates: dict[str, Any] = {}
    if enhancement_level is not ...:
        if enhancement_level is not None:
            level = int(enhancement_level)
            if level < 0 or level > 200:
                raise ValueError(
                    f"enhancement_level must be 0..200; got {level}"
                )
            updates["enhancement_level"] = level
        else:
            updates["enhancement_level"] = None
    if mastery_level is not ...:
        if mastery_level is not None:
            level = int(mastery_level)
            if level < 0 or level > 20:
                raise ValueError(f"mastery_level must be 0..20; got {level}")
            updates["mastery_level"] = level
        else:
            updates["mastery_level"] = None
    if rarity is not ...:
        updates["rarity"] = normalize_ui_rarity(
            None if rarity is None else str(rarity)
        )
    if slot is not ...:
        updates["slot"] = normalize_ui_slot(
            None if slot is None else str(slot)
        )

    if not updates:
        return piece
    updated = sync_piece_power(replace(piece, **updates))
    overwrite = frozenset(updates.keys()) | {"power"}
    return store.upsert(updated, overwrite=overwrite)


def sync_all_powers(store: GearStore) -> int:
    """Recompute and persist power for every piece; return count changed."""
    changed = 0
    for piece in store.all_pieces():
        synced = sync_piece_power(piece)
        if synced.power != piece.power:
            store.upsert(synced)
            changed += 1
    return changed


def update_hero_stars(
    store: HeroStore,
    name: str,
    *,
    stars: int | None | object = ...,
    pellets: int | None | object = ...,
    power: int | None | object = ...,
    level: int | None | object = ...,
) -> HeroRecord:
    """Update stars/pellets/power/level.

    When stars/pellets change and ``power`` is omitted, rescale power via
    ``star_progress_factor``. Explicit ``power`` always wins (OCR fixes).
    Level is stored only — no invented level→power formula.
    """
    heroes = {h.name: h for h in store.all_heroes()}
    hero = heroes.get(name)
    if hero is None:
        raise KeyError(name)

    new_stars = hero.stars
    new_pellets = hero.pellets
    new_power = hero.power
    new_level = hero.level
    power_explicit = False

    if stars is not ...:
        if stars is not None:
            value = int(stars)
            if value not in _STARS_RANGE:
                raise ValueError(f"stars must be 0..5; got {value}")
            new_stars = value
        else:
            new_stars = None
    if pellets is not ...:
        if pellets is not None:
            value = int(pellets)
            if value not in _PELLETS_RANGE:
                raise ValueError(f"pellets must be 0..5; got {value}")
            new_pellets = value
        else:
            new_pellets = None
    if level is not ...:
        if level is not None:
            value = int(level)
            if value not in _HERO_LEVEL_RANGE:
                raise ValueError(f"level must be 1..80; got {value}")
            new_level = value
        else:
            new_level = None
    if power is not ...:
        power_explicit = True
        if power is not None:
            value = int(power)
            if value < _POWER_MIN or value > _POWER_MAX:
                raise ValueError(
                    f"power must be {_POWER_MIN}..{_POWER_MAX}; got {value}"
                )
            new_power = value
        else:
            new_power = None

    stars_changed = new_stars != hero.stars or new_pellets != hero.pellets
    if stars_changed and not power_explicit:
        new_power = scale_power_for_star_change(
            hero.power,
            hero.stars,
            hero.pellets,
            new_stars,
            new_pellets,
        )

    if (
        new_stars == hero.stars
        and new_pellets == hero.pellets
        and new_power == hero.power
        and new_level == hero.level
    ):
        return hero

    new_assurance = dict(hero.assurance)
    if new_stars != hero.stars:
        new_assurance = set_field(new_assurance, "stars", "high", "manual_confirm")
    if new_pellets != hero.pellets:
        new_assurance = set_field(new_assurance, "pellets", "high", "manual_confirm")
    if new_level != hero.level:
        new_assurance = set_field(new_assurance, "level", "high", "manual_confirm")
    if power_explicit and new_power != hero.power:
        new_assurance = set_field(new_assurance, "power", "high", "manual_confirm")
    elif stars_changed and not power_explicit and new_power != hero.power:
        new_assurance = set_field(new_assurance, "power", "medium", "scaled_from_stars")

    updated = replace(
        hero,
        stars=new_stars,
        pellets=new_pellets,
        power=new_power,
        level=new_level,
        assurance=new_assurance,
    )
    overwrite = frozenset(
        f
        for f, before, after in (
            ("stars", hero.stars, new_stars),
            ("pellets", hero.pellets, new_pellets),
            ("power", hero.power, new_power),
            ("level", hero.level, new_level),
        )
        if before != after
    )
    store.upsert(updated, overwrite=overwrite)
    return updated


def update_hero_skills(
    store: HeroStore,
    name: str,
    skills_raw: list[dict[str, Any]],
) -> HeroRecord:
    """Replace hero skills; levels must be 1..5. Overwrites OCR skill rows."""
    from ks.heroes.models import SkillRecord

    heroes = {h.name: h for h in store.all_heroes()}
    hero = heroes.get(name)
    if hero is None:
        raise KeyError(name)
    if not isinstance(skills_raw, list) or not skills_raw:
        raise ValueError("skills must be a non-empty list")
    skills: list[SkillRecord] = []
    seen_slots: set[int] = set()
    for item in skills_raw:
        if not isinstance(item, dict):
            raise ValueError("each skill must be a mapping")
        slot = int(item["slot"])
        if slot in seen_slots:
            raise ValueError(f"duplicate skill slot {slot}")
        seen_slots.add(slot)
        level = item.get("level")
        if level is None:
            raise ValueError(f"skill slot {slot} requires level 1..5")
        level_i = int(level)
        if level_i < 1 or level_i > 5:
            raise ValueError(f"skill level must be 1..5; got {level_i} for slot {slot}")
        name_s = str(item.get("name") or "").strip() or None
        skills.append(
            SkillRecord(
                slot=slot,
                name=name_s,
                level=level_i,
                description=item.get("description"),
                upgrade_preview=item.get("upgrade_preview"),
                current_bonus=(
                    float(item["current_bonus"])
                    if item.get("current_bonus") is not None
                    else None
                ),
                raw_text=item.get("raw_text"),
            )
        )
    skills.sort(key=lambda s: s.slot)
    updated = replace(hero, skills=tuple(skills))
    store.upsert(updated, overwrite=frozenset({"skills"}))
    return updated


def create_app(
    gear_dir: Path | None = None,
    *,
    heroes_dir: Path | None = None,
    troops_path: Path | None = None,
    governor_dir: Path | None = None,
    research_dir: Path | None = None,
    gear_config: Path | None = None,
    heroes_config: Path | None = None,
    serial: str | None = None,
    rescan_fn: Callable[..., list[GearRecord]] | None = None,
    heroes_rescan_fn: Callable[..., list[HeroRecord]] | None = None,
    auth_config: Any = None,
    users_root: Path | None = None,
    http_client_factory: Any = None,
) -> Any:
    """Build FastAPI app bound to gear and/or heroes inventory directories.

    When ``auth_config`` (an ``AuthConfig``) is provided the auth shell is
    installed: SessionMiddleware + protect middleware + ``/auth/*`` routes.
    Inventory directories become optional in auth mode — per-request binding
    arrives in Task 5; endpoints that need stores return 503 until then.
    """
    if FastAPI is None:
        raise ImportError(
            "UI dependencies missing; install with: pip install 'ks[ui]'"
        )
    if auth_config is None and gear_dir is None and heroes_dir is None:
        raise ValueError("gear_dir or heroes_dir is required")

    resolved_gear = _resolve_gear_dir(gear_dir) if gear_dir is not None else None
    resolved_heroes = (
        _resolve_heroes_dir(heroes_dir) if heroes_dir is not None else None
    )
    gear_store = GearStore(resolved_gear) if resolved_gear is not None else None
    hero_store = (
        HeroStore(resolved_heroes) if resolved_heroes is not None else None
    )
    # Troops live alongside heroes when both halves are configured — heroes
    # is what the optimisers actually consume troops for — else alongside
    # gear. `troops_path` (CLI `--troops`) overrides the location outright.
    # In auth mode without any inventory dir the store is deferred to Task 5;
    # endpoints that need it return 503 until per-request binding lands.
    troops_dir = resolved_heroes if resolved_heroes is not None else resolved_gear
    if troops_dir is None and troops_path is None:
        troop_store = None
    else:
        troop_store = TroopStore(
            troops_path.expanduser().resolve()
            if troops_path is not None
            else troops_dir / "troops.yaml",  # type: ignore[operator]
            seed_from=REPO_ROOT / "config" / "troops.yaml",
        )
        troop_store.ensure_exists()
    from ks.heroes.governor_store import GovernorGearStore
    from ks.heroes.research_store import ResearchStore

    if governor_dir is not None:
        resolved_governor = governor_dir.expanduser().resolve()
    elif resolved_heroes is not None and resolved_heroes.parent.name == "heroes":
        resolved_governor = (
            resolved_heroes.parent.parent / "governor" / "full-run"
        ).resolve()
    else:
        resolved_governor = (REPO_ROOT / "data" / "governor" / "full-run").resolve()
    governor_store = GovernorGearStore(resolved_governor)

    if research_dir is not None:
        resolved_research = research_dir.expanduser().resolve()
    elif resolved_heroes is not None and resolved_heroes.parent.name == "heroes":
        resolved_research = (
            resolved_heroes.parent.parent / "research" / "full-run"
        ).resolve()
    else:
        resolved_research = (REPO_ROOT / "data" / "research" / "full-run").resolve()
    research_store = ResearchStore(resolved_research)
    gear_config_path = (gear_config or DEFAULT_GEAR_CONFIG).expanduser().resolve()
    heroes_config_path = (
        (heroes_config or DEFAULT_HEROES_CONFIG).expanduser().resolve()
    )
    do_gear_rescan = rescan_fn or rescan_gear_from_ocr
    do_heroes_rescan = heroes_rescan_fn or rescan_heroes_from_ocr
    gear_rescan_lock = threading.Lock()
    heroes_rescan_lock = threading.Lock()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app = FastAPI(title="KS Heroes UI", version="0.2.0")
    app.state.gear_dir = resolved_gear
    app.state.heroes_dir = resolved_heroes
    app.state.governor_dir = resolved_governor
    app.state.research_dir = resolved_research
    app.state.store = gear_store
    app.state.hero_store = hero_store
    app.state.governor_store = governor_store
    app.state.research_store = research_store
    app.state.gear_config = gear_config_path
    app.state.heroes_config = heroes_config_path
    app.state.serial = serial
    app.state.troops_path = troop_store.path if troop_store is not None else None
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    if resolved_gear is not None:
        icons_path = resolved_gear / "icons"
        icons_path.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/icons",
            StaticFiles(directory=str(icons_path)),
            name="icons",
        )
    if resolved_heroes is not None:
        hero_icons_path = resolved_heroes / "icons"
        hero_icons_path.mkdir(parents=True, exist_ok=True)
        app.mount(
            "/hero-icons",
            StaticFiles(directory=str(hero_icons_path)),
            name="hero_icons",
        )
    # In auth mode there is no single icons dir at startup; serve per-user icons
    # dynamically via FileResponse so user A's icons never leak to user B.
    if auth_config is not None:
        from fastapi.responses import FileResponse as _FileResponse

        @app.get("/icons/{path:path}", include_in_schema=False)
        def serve_user_icons(path: str) -> Any:
            from ks.auth.request_inventory import get_current_inventory
            inv = get_current_inventory()
            if inv is None:
                raise HTTPException(status_code=404, detail="no inventory")
            icons_root = (inv.gear_dir / "icons").resolve()
            safe = _safe_under(icons_root, path)
            if safe is None:
                raise HTTPException(status_code=404, detail=f"icon not found: {path}")
            return _FileResponse(str(safe))

        @app.get("/hero-icons/{path:path}", include_in_schema=False)
        def serve_user_hero_icons(path: str) -> Any:
            from ks.auth.request_inventory import get_current_inventory
            inv = get_current_inventory()
            if inv is None:
                raise HTTPException(status_code=404, detail="no inventory")
            icons_root = (inv.heroes_dir / "icons").resolve()
            safe = _safe_under(icons_root, path)
            if safe is None:
                raise HTTPException(status_code=404, detail=f"hero icon not found: {path}")
            return _FileResponse(str(safe))

    def _require_gear() -> tuple[Path, GearStore]:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        if inv is not None:
            return inv.gear_dir, inv.store
        if resolved_gear is None or gear_store is None:
            raise HTTPException(status_code=404, detail="gear UI not configured")
        return resolved_gear, gear_store

    def _require_heroes() -> tuple[Path, HeroStore]:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        if inv is not None:
            return inv.heroes_dir, inv.hero_store
        if resolved_heroes is None or hero_store is None:
            raise HTTPException(
                status_code=404, detail="heroes UI not configured"
            )
        return resolved_heroes, hero_store

    def _require_troop_store():
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        if inv is not None:
            return inv.troop_store
        if troop_store is None:
            raise HTTPException(
                status_code=503,
                detail="troops store not configured",
            )
        return troop_store

    def _require_governor_store():
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        return inv.governor_store if inv is not None else governor_store

    def _require_research_store():
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        return inv.research_store if inv is not None else research_store

    def _current_troops_path() -> Path | None:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        if inv is not None:
            return inv.troops_path
        return troop_store.path if troop_store is not None else None

    def _current_gear_store() -> GearStore | None:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        return inv.store if inv is not None else gear_store

    def _current_gear_dir() -> Path | None:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        return inv.gear_dir if inv is not None else resolved_gear

    def _current_governor_dir() -> Path:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        return inv.governor_dir if inv is not None else resolved_governor

    def _current_research_dir() -> Path:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        return inv.research_dir if inv is not None else resolved_research

    def _current_hero_store() -> HeroStore | None:
        from ks.auth.request_inventory import get_current_inventory
        inv = get_current_inventory()
        return inv.hero_store if inv is not None else hero_store

    def _shell_page(
        request: Request,
        template: str,
        *,
        primary: str,
        subtab: str,
        **extra: Any,
    ) -> HTMLResponse:
        """Render a page inside the Inventory/Optimiser shell (never cached)."""
        from ks.auth.request_inventory import get_current_inventory
        _inv = get_current_inventory()
        context: dict[str, Any] = {
            "primary": primary,
            "subtab": subtab,
            "gear_enabled": _inv is not None or resolved_gear is not None,
            "heroes_enabled": _inv is not None or resolved_heroes is not None,
        }
        context.update(extra)
        from ks.heroes.ui.path_display import mask_path_fields

        context = mask_path_fields(context)
        response = templates.TemplateResponse(request, template, context)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        from ks.auth.request_inventory import get_current_inventory
        if resolved_gear is not None or get_current_inventory() is not None:
            return RedirectResponse(url="/inventory/gear", status_code=302)
        return RedirectResponse(url="/inventory/heroes", status_code=302)

    # Legacy paths kept for bookmarks; the IA lives under /inventory and
    # /optimiser now.
    @app.get("/gear", include_in_schema=False)
    def legacy_gear() -> RedirectResponse:
        return RedirectResponse(url="/inventory/gear", status_code=302)

    @app.get("/heroes", include_in_schema=False)
    def legacy_heroes() -> RedirectResponse:
        return RedirectResponse(url="/inventory/heroes", status_code=302)

    @app.get("/optimize", include_in_schema=False)
    def legacy_optimize() -> RedirectResponse:
        return RedirectResponse(url="/optimiser/events", status_code=302)

    @app.get("/optimize/events", include_in_schema=False)
    def legacy_optimize_events() -> RedirectResponse:
        return RedirectResponse(url="/optimiser/events", status_code=302)

    @app.get("/optimize/gear-xp", include_in_schema=False)
    def legacy_optimize_gear_xp() -> RedirectResponse:
        return RedirectResponse(url="/optimiser/gear-xp", status_code=302)

    @app.get("/inventory/gear", response_class=HTMLResponse)
    def inventory_gear_page(request: Request) -> HTMLResponse:
        gear_path, store = _require_gear()
        store.reload()
        pieces = store.all_pieces()
        bust = inventory_revision(gear_path, "gear.json")
        icon_map = {
            pid: with_cache_bust(url, bust)
            for pid, url in ensure_all_icons(pieces, gear_path).items()
        }
        return _shell_page(
            request,
            "inventory_gear.html",
            primary="inventory",
            subtab="gear",
            pieces=pieces,
            icons=icon_map,
            gear_dir=str(gear_path),
            cache_bust=bust,
            # "Needs attention" has to work on a plain page load, before any
            # rescan has put a trust payload in sessionStorage — so the same
            # predicate the rescan diff uses runs here, and the browser
            # never carries a second copy of the rarity gate.
            incomplete_ids={
                p.piece_id for p in pieces if gear_row_incomplete(p)
            },
            mastery_required_ids={
                p.piece_id for p in pieces if gear_mastery_required(p.rarity)
            },
            # The two pickers restored from the pre-merge page. Values are
            # normalised here rather than in Jinja so the `selected` option
            # is decided by the same function the PATCH endpoint validates
            # with; `None` means "this store value has no option" — see
            # ui_select_value.
            rarity_options=UI_RARITY_CHOICES,
            slot_options=UI_SLOT_CHOICES,
            rarity_values={
                p.piece_id: ui_select_value(p.rarity, normalize_ui_rarity)
                for p in pieces
            },
            slot_values={
                p.piece_id: ui_select_value(p.slot, normalize_ui_slot)
                for p in pieces
            },
            # Lowercased before de-duplication: the chip's data-filter and
            # the row's data-troop are both `|lower`ed, so "Cavalry" and
            # "cavalry" would otherwise render two chips filtering identically.
            troop_types=sorted(
                {p.troop_type.lower() for p in pieces if p.troop_type}
            ),
        )

    @app.get("/inventory/heroes", response_class=HTMLResponse)
    def inventory_heroes_page(request: Request) -> HTMLResponse:
        heroes_path, store = _require_heroes()
        store.reload()
        heroes = store.all_heroes()
        bust = inventory_revision(heroes_path, "heroes.json")
        icon_map = {
            name: with_cache_bust(url, bust)
            for name, url in ensure_all_hero_icons(heroes, heroes_path).items()
        }
        return _shell_page(
            request,
            "inventory_heroes.html",
            primary="inventory",
            subtab="heroes",
            heroes=heroes,
            icons=icon_map,
            heroes_dir=str(heroes_path),
            cache_bust=bust,
            incomplete_names={
                h.name for h in heroes if hero_row_incomplete(h)
            },
            troop_types=sorted(
                {h.troop_type.lower() for h in heroes if h.troop_type}
            ),
            catalog_add_heroes=catalog_heroes_available_to_add(store),
        )

    @app.get("/inventory/troops", response_class=HTMLResponse)
    def inventory_troops_page(request: Request) -> HTMLResponse:
        """Server-render the troops editor from the store.

        Unlike GET /api/troops, an unreadable or invalid document must not
        take the *page* down: the editor is where a user repairs it (a
        complete PUT is self-healing over corrupt YAML), so a load failure
        renders the form with whatever was readable plus a banner carrying
        the validator's message. Validation runs through _troop_totals, the
        same path the API uses, so page and API never disagree about what
        counts as broken.
        """
        store = _require_troop_store()
        raw: dict[str, Any] = {}
        load_error: str | None = None
        try:
            raw = store.load_raw()
            _troop_totals(raw)
        except (yaml.YAMLError, ValueError, TypeError) as exc:
            load_error = str(exc)
        return _shell_page(
            request,
            "inventory_troops.html",
            primary="inventory",
            subtab="troops",
            form=troops_form_model(raw),
            troops_path=str(store.path),
            load_error=load_error,
        )

    @app.get("/inventory/governor-gear", response_class=HTMLResponse)
    def inventory_governor_gear_page(request: Request) -> HTMLResponse:
        gov_store = _require_governor_store()
        summary = gov_store.summary()
        return _shell_page(
            request,
            "inventory_governor_gear.html",
            primary="inventory",
            subtab="governor",
            summary=summary,
            governor_dir=str(_current_governor_dir()),
        )

    @app.get("/inventory/research", response_class=HTMLResponse)
    def inventory_research_page(request: Request) -> HTMLResponse:
        res_store = _require_research_store()
        summary = res_store.summary()
        return _shell_page(
            request,
            "inventory_research.html",
            primary="inventory",
            subtab="research",
            summary=summary,
            research_dir=str(_current_research_dir()),
        )

    @app.get("/api/governor-gear")
    def api_governor_gear() -> dict[str, Any]:
        return _require_governor_store().summary()

    @app.get("/api/research")
    def api_research_get() -> dict[str, Any]:
        return _require_research_store().summary()

    @app.put("/api/research")
    def api_research_put(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        res_store = _require_research_store()
        try:
            res_store.update_from_dict(body)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return res_store.summary()

    @app.post("/api/governor-gear/{slot_id}/upgrade")
    def api_governor_upgrade(slot_id: str) -> dict[str, Any]:
        gov_store = _require_governor_store()
        try:
            gov_store.upgrade(slot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return gov_store.summary()

    @app.patch("/api/governor-gear/{slot_id}")
    def api_governor_patch(slot_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from ks.heroes.governor_models import GovernorPiece

        gov_store = _require_governor_store()
        if slot_id not in gov_store.cfg.slots:
            raise HTTPException(status_code=404, detail=f"unknown slot {slot_id}")
        tier = body.get("tier")
        stars = body.get("stars")
        prev = gov_store.get(slot_id)
        assert prev is not None
        try:
            gov_store.upsert(
                GovernorPiece(
                    slot_id=slot_id,
                    tier=str(tier if tier is not None else prev.tier),
                    stars=int(stars if stars is not None else prev.stars),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return gov_store.summary()

    @app.get("/optimiser/events", response_class=HTMLResponse)
    def optimiser_events_page(request: Request) -> HTMLResponse:
        heroes_path, _ = _require_heroes()
        return _shell_page(
            request,
            "optimiser_events.html",
            primary="optimiser",
            subtab="events",
            heroes_dir=str(heroes_path),
        )

    @app.get("/optimiser/events/mystic-trial", response_class=HTMLResponse)
    def optimiser_mystic_trial_hub() -> RedirectResponse:
        return RedirectResponse(
            url="/optimiser/events/mystic-trial/radiant-spire",
            status_code=302,
        )

    @app.get(
        "/optimiser/events/mystic-trial/radiant-spire",
        response_class=HTMLResponse,
    )
    def optimiser_radiant_page(request: Request) -> HTMLResponse:
        heroes_path, _ = _require_heroes()
        return _shell_page(
            request,
            "optimiser_radiant_spire.html",
            primary="optimiser",
            subtab="events",
            mystic_room="radiant",
            heroes_dir=str(heroes_path),
            governor_dir=str(_current_governor_dir()),
        )

    @app.get(
        "/optimiser/events/mystic-trial/coliseum",
        response_class=HTMLResponse,
    )
    def optimiser_coliseum_page(request: Request) -> HTMLResponse:
        heroes_path, _ = _require_heroes()
        return _shell_page(
            request,
            "optimiser_coliseum.html",
            primary="optimiser",
            subtab="events",
            mystic_room="coliseum",
            heroes_dir=str(heroes_path),
            governor_dir=str(_current_governor_dir()),
        )

    @app.get(
        "/optimiser/events/mystic-trial/molten-fort",
        response_class=HTMLResponse,
    )
    def optimiser_molten_page(request: Request) -> HTMLResponse:
        heroes_path, _ = _require_heroes()
        return _shell_page(
            request,
            "optimiser_molten_fort.html",
            primary="optimiser",
            subtab="events",
            mystic_room="molten",
            heroes_dir=str(heroes_path),
            governor_dir=str(_current_governor_dir()),
        )

    @app.get("/optimiser/radiant-spire", response_class=HTMLResponse)
    def optimiser_radiant_legacy() -> RedirectResponse:
        return RedirectResponse(
            url="/optimiser/events/mystic-trial/radiant-spire",
            status_code=302,
        )

    @app.get("/optimiser/coliseum", response_class=HTMLResponse)
    def optimiser_coliseum_legacy() -> RedirectResponse:
        return RedirectResponse(
            url="/optimiser/events/mystic-trial/coliseum",
            status_code=302,
        )

    @app.get("/optimiser/molten-fort", response_class=HTMLResponse)
    def optimiser_molten_legacy() -> RedirectResponse:
        return RedirectResponse(
            url="/optimiser/events/mystic-trial/molten-fort",
            status_code=302,
        )

    @app.get("/optimiser/gear-xp", response_class=HTMLResponse)
    def optimiser_gear_xp_page(request: Request) -> HTMLResponse:
        heroes_path, _ = _require_heroes()
        # Both lists the form offers are read off the same config the spend
        # search itself consumes, never transcribed into the template:
        #   - fodder XP values from pieces_and_stats.yaml, so the "30 XP each"
        #     note beside a box cannot outlive a retune of that file;
        #   - mode keys from the point-scenario files build_event_utility()
        #     passes to recommend(), so the picker can never offer a mode the
        #     optimiser would reject with a 400.
        # Read per request rather than at startup: these are hand-edited
        # tuning files and the page is already no-store.
        #
        # And read defensively, for the same reason. Reading per request is
        # only useful if the page survives a bad edit: unguarded, a typo in
        # one of these three files 500s the whole screen — including the
        # fodder boxes and the run button, which have nothing to do with the
        # file that broke. Each load degrades on its own (no XP notes, or an
        # empty mode list) and the page names what it could not read.
        from ks.heroes.optimize.scenarios import load_scenarios
        from ks.heroes.optimize.xp_ladder import load_fodder_xp_values

        events_dir = REPO_ROOT / "config"
        tuning_errors: list[str] = []

        def _tuned(what: str, load: Callable[[], Any], fallback: Any) -> Any:
            try:
                return load()
            except TUNING_ERRORS as exc:
                tuning_errors.append(f"{what} ({exc})")
                return fallback

        fodder_xp = _tuned("fodder XP values", load_fodder_xp_values, {})
        sword_modes = _tuned(
            "Swordland modes",
            lambda: list(load_scenarios(events_dir / "point_scenarios.yaml")),
            [],
        )
        bear_modes = _tuned(
            "Bear Trap modes",
            lambda: list(load_scenarios(events_dir / "point_scenarios_beartrap.yaml")),
            [],
        )
        return _shell_page(
            request,
            "optimiser_gear_xp.html",
            primary="optimiser",
            subtab="gear-xp",
            heroes_dir=str(heroes_path),
            gear_dir=str(resolved_gear) if resolved_gear is not None else None,
            fodder_xp=fodder_xp,
            sword_modes=sword_modes,
            bear_modes=bear_modes,
            tuning_error="; ".join(tuning_errors) or None,
        )

    @app.get("/optimiser/hero-levels", response_class=HTMLResponse)
    def optimiser_hero_levels_page(request: Request) -> HTMLResponse:
        _require_heroes()
        return _shell_page(
            request,
            "optimiser_hero_levels.html",
            primary="optimiser",
            subtab="hero-levels",
        )

    @app.get("/api/gear")
    def api_list_gear() -> dict[str, Any]:
        gear_path, store = _require_gear()
        store.reload()
        pieces = store.all_pieces()
        bust = inventory_revision(gear_path, "gear.json")
        icon_map = ensure_all_icons(pieces, gear_path)
        return {
            "cache_bust": bust,
            "gear": [
                {
                    **p.to_dict(),
                    "icon_url": with_cache_bust(icon_map.get(p.piece_id), bust),
                }
                for p in pieces
            ],
        }

    @app.post("/api/gear")
    async def api_create_gear(request: Request) -> dict[str, Any]:
        """Manually add a piece (troop × slot × rarity); name from gear_names.yaml."""
        gear_path, store = _require_gear()
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            piece = create_manual_piece(
                store,
                troop_type=str(raw.get("troop_type") or ""),
                slot=str(raw.get("slot") or ""),
                rarity=str(raw.get("rarity") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        bust = inventory_revision(gear_path, "gear.json")
        icon_map = ensure_all_icons([piece], gear_path)
        return {
            "ok": True,
            "piece": {
                **piece.to_dict(),
                "icon_url": with_cache_bust(icon_map.get(piece.piece_id), bust),
            },
        }

    @app.post("/api/gear/rescan")
    def api_rescan_gear() -> dict[str, Any]:
        """Replace inventory via ADB OCR (Backpack > Gear must be open)."""
        gear_path, store = _require_gear()
        if not gear_rescan_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="gear rescan already in progress",
            )
        try:
            # Snapshot before the rescan touches the store, so the trust
            # diff below compares "what was here" to "what OCR just saw"
            # rather than the new state against itself.
            store.reload()
            before = store.all_pieces()
            pieces = do_gear_rescan(
                store,
                config_path=gear_config_path,
                serial=serial,
            )
            store.reload()
            pieces = store.all_pieces()
            icons_path = gear_path / "icons"
            if icons_path.is_dir():
                shutil.rmtree(icons_path)
            icons_path.mkdir(parents=True, exist_ok=True)
            json_path = gear_path / "gear.json"
            if json_path.is_file():
                now = time.time()
                os.utime(json_path, (now, now))
        except Exception as exc:  # noqa: BLE001 — surface ADB/OCR failures to UI
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            gear_rescan_lock.release()
        bust = inventory_revision(gear_path, "gear.json")
        icon_map = ensure_all_icons(pieces, gear_path)
        trust = summarize_flags(flag_gear_rows(before, pieces))
        return {
            "ok": True,
            "count": len(pieces),
            "trust": trust,
            "cache_bust": bust,
            "gear": [
                {
                    **p.to_dict(),
                    "icon_url": with_cache_bust(icon_map.get(p.piece_id), bust),
                }
                for p in pieces
            ],
        }

    @app.delete("/api/gear/{piece_id}")
    def api_delete_gear(piece_id: str) -> dict[str, Any]:
        """Remove a consumed or stale piece from the inventory."""
        _, store = _require_gear()
        deleted = store.delete(piece_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"piece not found: {piece_id}")
        return {"ok": True, "deleted": piece_id}

    @app.patch("/api/gear/{piece_id}")
    async def api_patch_gear(piece_id: str, request: Request) -> dict[str, Any]:
        gear_path, store = _require_gear()
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")

        enh_arg: Any = ...
        mast_arg: Any = ...
        rarity_arg: Any = ...
        slot_arg: Any = ...
        if raw.get("clear_enhancement"):
            enh_arg = None
        elif "enhancement_level" in raw:
            enh_arg = raw.get("enhancement_level")
        if raw.get("clear_mastery"):
            mast_arg = None
        elif "mastery_level" in raw:
            mast_arg = raw.get("mastery_level")
        if raw.get("clear_rarity"):
            rarity_arg = None
        elif "rarity" in raw:
            rarity_arg = raw.get("rarity")
        if raw.get("clear_slot"):
            slot_arg = None
        elif "slot" in raw:
            slot_arg = raw.get("slot")

        try:
            updated = update_piece_levels(
                store,
                piece_id,
                enhancement_level=enh_arg,
                mastery_level=mast_arg,
                rarity=rarity_arg,
                slot=slot_arg,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"unknown piece_id: {piece_id}"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        icon_url = ensure_all_icons([updated], gear_path).get(piece_id)
        return {
            "ok": True,
            "piece": {**updated.to_dict(), "icon_url": icon_url},
        }

    @app.get("/api/heroes")
    def api_list_heroes() -> dict[str, Any]:
        heroes_path, store = _require_heroes()
        store.reload()
        heroes = store.all_heroes()
        bust = inventory_revision(heroes_path, "heroes.json")
        icon_map = ensure_all_hero_icons(heroes, heroes_path)
        return {
            "cache_bust": bust,
            "heroes": [
                {
                    **h.to_dict(),
                    "icon_url": with_cache_bust(icon_map.get(h.name), bust),
                }
                for h in heroes
            ],
        }

    @app.post("/api/heroes")
    async def api_create_hero(request: Request) -> dict[str, Any]:
        """Manually add a catalog hero to the roster."""
        _heroes_path, store = _require_heroes()
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            hero = create_manual_hero(store, name=str(raw.get("name") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "hero": hero.to_dict()}

    @app.get("/api/heroes/{name}")

    def api_get_hero(name: str) -> dict[str, Any]:
        heroes_path, store = _require_heroes()
        store.reload()
        hero = next((h for h in store.all_heroes() if h.name == name), None)
        if hero is None:
            raise HTTPException(status_code=404, detail=f"unknown hero: {name}")
        bust = inventory_revision(heroes_path, "heroes.json")
        icon_url = with_cache_bust(
            ensure_all_hero_icons([hero], heroes_path).get(name), bust
        )
        from ks.heroes.optimize.catalog import load_catalog

        catalog = load_catalog(None, REPO_ROOT / "config" / "hero_catalog.yaml")
        entry = catalog.get(name)
        catalog_skills = (
            [s.to_dict() for s in entry.skills] if entry is not None else []
        )
        return {
            "hero": {**hero.to_dict(), "icon_url": icon_url},
            "catalog_skills": catalog_skills,
        }

    @app.patch("/api/heroes/{name}/skills")
    async def api_patch_hero_skills(name: str, request: Request) -> dict[str, Any]:
        heroes_path, store = _require_heroes()
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        skills_raw = raw.get("skills")
        if not isinstance(skills_raw, list):
            raise HTTPException(status_code=400, detail="skills must be a list")
        try:
            updated = update_hero_skills(store, name, skills_raw)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"unknown hero: {name}"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        icon_url = ensure_all_hero_icons([updated], heroes_path).get(name)
        from ks.heroes.optimize.catalog import load_catalog

        catalog = load_catalog(None, REPO_ROOT / "config" / "hero_catalog.yaml")
        entry = catalog.get(name)
        catalog_skills = (
            [s.to_dict() for s in entry.skills] if entry is not None else []
        )
        return {
            "ok": True,
            "hero": {**updated.to_dict(), "icon_url": icon_url},
            "catalog_skills": catalog_skills,
        }

    @app.patch("/api/heroes/{name}")
    async def api_patch_hero(name: str, request: Request) -> dict[str, Any]:
        heroes_path, store = _require_heroes()
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")

        stars_arg: Any = ...
        pellets_arg: Any = ...
        power_arg: Any = ...
        level_arg: Any = ...
        if "stars" in raw:
            stars_arg = raw.get("stars")
        if "pellets" in raw:
            pellets_arg = raw.get("pellets")
        if "power" in raw:
            power_arg = raw.get("power")
        if "level" in raw:
            level_arg = raw.get("level")

        try:
            updated = update_hero_stars(
                store,
                name,
                stars=stars_arg,
                pellets=pellets_arg,
                power=power_arg,
                level=level_arg,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"unknown hero: {name}"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        icon_url = ensure_all_hero_icons([updated], heroes_path).get(name)
        return {
            "ok": True,
            "hero": {**updated.to_dict(), "icon_url": icon_url},
        }

    @app.post("/api/heroes/rescan")
    def api_rescan_heroes() -> dict[str, Any]:
        """Upsert roster via ADB OCR (Heroes roster must be open)."""
        heroes_path, store = _require_heroes()
        if not heroes_rescan_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="heroes rescan already in progress",
            )
        try:
            # Snapshot before the rescan upserts into the store: heroes
            # rescans never wipe the roster, so "new" must mean "not in the
            # pre-rescan snapshot," not "not in the file we just wrote."
            store.reload()
            before = store.all_heroes()
            do_heroes_rescan(
                store,
                config_path=heroes_config_path,
                serial=serial,
            )
            store.reload()
            heroes = store.all_heroes()
            json_path = heroes_path / "heroes.json"
            if json_path.is_file():
                now = time.time()
                os.utime(json_path, (now, now))
        except Exception as exc:  # noqa: BLE001 — surface ADB/OCR failures to UI
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            heroes_rescan_lock.release()
        bust = inventory_revision(heroes_path, "heroes.json")
        icon_map = ensure_all_hero_icons(heroes, heroes_path)
        trust = summarize_flags(flag_hero_rows(before, heroes))
        return {
            "ok": True,
            "count": len(heroes),
            "trust": trust,
            "cache_bust": bust,
            "heroes": [
                {
                    **h.to_dict(),
                    "icon_url": with_cache_bust(icon_map.get(h.name), bust),
                }
                for h in heroes
            ],
        }

    @app.get("/api/troops")
    def api_get_troops() -> dict[str, Any]:
        """Return the on-disk troops document and its computed totals.

        The file is hand-editable YAML in the user's data dir, and
        save_raw()'s writer is a non-atomic write_text, so either a hand
        edit or an interrupted save can leave content that fails to parse
        or fails validation. Surface that as 422 with the underlying
        message (matching the PUT-side validation error) instead of a
        blank 500, so the user can see what to repair.
        """
        store = _require_troop_store()
        try:
            raw = store.load_raw()
            totals = _troop_totals(raw)
        except (yaml.YAMLError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"troops": raw, "totals": totals}

    @app.put("/api/troops")
    async def api_put_troops(request: Request) -> dict[str, Any]:
        """Merge the request body into the existing troops document.

        See TroopStore.save_raw for the exact merge contract: keys present
        in the body replace their counterparts; keys the body omits are
        preserved from the existing document (so omitting truegold does not
        delete it); a present type block (infantry/cavalry/archers) replaces
        that whole block rather than being deep-merged tier by tier. Task
        3's editor page is built against this contract.
        """
        store = _require_troop_store()
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            saved = store.save_raw(raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"troops": saved, "totals": _troop_totals(saved)}

    @app.get("/api/optimize")
    def api_optimize() -> dict[str, Any]:
        """Sword/Bear all modes + Arena attack/defense from current inventory."""
        heroes_path, hero_store_local = _require_heroes()
        from ks.heroes.ui.optimize_run import (
            attach_gear_icon_urls,
            run_optimize_bundle,
        )

        hero_store_local.reload()
        heroes = hero_store_local.all_heroes()
        gear_pieces: list[GearRecord] | None = None
        icon_by_id: dict[str, str | None] = {}
        icon_warning: str | None = None
        eff_gear_store = _current_gear_store()
        eff_gear_dir = _current_gear_dir()
        if eff_gear_store is not None and eff_gear_dir is not None:
            eff_gear_store.reload()
            gear_pieces = eff_gear_store.all_pieces() or None
            if gear_pieces:
                try:
                    bust = inventory_revision(eff_gear_dir, "gear.json")
                    raw_icons = ensure_all_icons(gear_pieces, eff_gear_dir)
                    icon_by_id = {
                        pid: with_cache_bust(url, bust)
                        for pid, url in raw_icons.items()
                    }
                except Exception as exc:  # noqa: BLE001 — optimize without icons
                    icon_warning = f"gear icons unavailable: {exc}"
        gov_store = _require_governor_store()
        bundle = run_optimize_bundle(
            heroes,
            gear=gear_pieces,
            troops_path=_current_troops_path(),
            governor=gov_store.bonuses() if gov_store is not None else None,
        )
        if icon_by_id:
            attach_gear_icon_urls(bundle, icon_by_id)
        if icon_warning:
            warnings = list(bundle.get("warnings") or [])
            warnings.append(icon_warning)
            bundle["warnings"] = warnings
        bundle["heroes_dir"] = str(heroes_path)
        return bundle

    @app.post("/api/optimize/beartrap/joiner")
    async def api_optimize_beartrap_joiner(request: Request) -> dict[str, Any]:
        """Re-solve Bear Trap joiner using an explicit hero allow-list."""
        from ks.heroes.ui.optimize_run import (
            attach_gear_icon_urls,
            run_beartrap_joiner,
        )

        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        allow = raw.get("allow_heroes")
        if not isinstance(allow, list) or not allow:
            raise HTTPException(
                status_code=400, detail="allow_heroes must be a non-empty list"
            )

        _heroes_path, hero_store_local = _require_heroes()
        hero_store_local.reload()
        heroes = hero_store_local.all_heroes()
        gear_pieces: list[GearRecord] | None = None
        icon_by_id: dict[str, str | None] = {}
        eff_gear_store = _current_gear_store()
        eff_gear_dir = _current_gear_dir()
        if eff_gear_store is not None and eff_gear_dir is not None:
            eff_gear_store.reload()
            gear_pieces = eff_gear_store.all_pieces() or None
            if gear_pieces:
                try:
                    bust = inventory_revision(eff_gear_dir, "gear.json")
                    raw_icons = ensure_all_icons(gear_pieces, eff_gear_dir)
                    icon_by_id = {
                        pid: with_cache_bust(url, bust)
                        for pid, url in raw_icons.items()
                    }
                except Exception:  # noqa: BLE001
                    icon_by_id = {}
        gov_store = _require_governor_store()
        try:
            payload = run_beartrap_joiner(
                heroes,
                allow_heroes=[str(n) for n in allow],
                gear=gear_pieces,
                troops_path=_current_troops_path(),
                governor=gov_store.bonuses() if gov_store is not None else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if icon_by_id:
            # attach expects a full optimize bundle; wrap joiner row shape
            mini = {"bear": {"modes": {"joiner": payload}}}
            attach_gear_icon_urls(mini, icon_by_id)
            payload = mini["bear"]["modes"]["joiner"]
        return payload

    @app.get("/api/optimize/radiant-spire")
    def api_optimize_radiant(
        stage: int | None = None,
        round: int | None = None,
        floor: int | None = None,
        enemy_infantry: float | None = None,
        enemy_cavalry: float | None = None,
        enemy_archers: float | None = None,
        enemy_bonuses: str | None = None,
    ) -> dict[str, Any]:
        """Dual-march Radiant Spire proxy from heroes, gear, troops, governor.

        Pass both ``stage`` and ``round`` to enable the opponent panel and MC
        stub (``floor`` is a deprecated alias for ``stage``). Optional enemy_*
        query parts override the stub ratio; saved opponents override when set.
        """
        import json

        from ks.heroes.optimize.mystic_trial.floors import (
            parse_enemy_bonuses,
            ratio_from_parts,
        )
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            get_player_bonuses,
            get_stage_round,
            load_store,
            opponents_path,
            ratio_from_counts,
        )
        from ks.heroes.ui.optimize_run import (
            apply_saved_radiant_opponents,
            attach_mystic_gear_icon_urls,
            resolve_mystic_player_event_troops,
            run_radiant_optimize,
        )

        heroes_path, hero_store_local = _require_heroes()
        hero_store_local.reload()
        heroes = hero_store_local.all_heroes()
        gear_pieces: list[GearRecord] = []
        eff_gear_store = _current_gear_store()
        if eff_gear_store is not None:
            eff_gear_store.reload()
            gear_pieces = eff_gear_store.all_pieces()

        # Both stage and round required for opponent panel / stub; floor aliases stage.
        stage_n = stage if stage is not None else floor
        round_n = round
        use_stage_round = stage_n is not None and round_n is not None
        gov_dir = _current_governor_dir()
        try:
            ratio_override = ratio_from_parts(
                enemy_infantry, enemy_cavalry, enemy_archers
            )
            bonuses_override = None
            if enemy_bonuses is not None and str(enemy_bonuses).strip():
                raw = json.loads(enemy_bonuses)
                bonuses_override = parse_enemy_bonuses(raw)
            saved_opponents = None
            player_report_bonuses = None
            player_event_troops = None
            if use_stage_round:
                store = load_store(opponents_path(gov_dir))
                saved_opponents = get_stage_round(
                    store,
                    int(stage_n),
                    int(round_n),
                )
                player_report_bonuses = get_player_bonuses(
                    store, int(stage_n), int(round_n)
                )
                player_event_troops = resolve_mystic_player_event_troops(
                    governor_dir=gov_dir,
                    stage=int(stage_n),
                    round_no=int(round_n),
                    room="radiant",
                    room_path=REPO_ROOT
                    / "config"
                    / "mystic_trial"
                    / "radiant_spire.yaml",
                )
                if saved_opponents and ratio_override is None:
                    for march in saved_opponents:
                        derived = ratio_from_counts(march["counts"])
                        if derived is not None:
                            ratio_override = derived
                            break
                    if bonuses_override is None:
                        bonuses_override = saved_opponents[0]["bonuses"]
            payload = run_radiant_optimize(
                heroes,
                governor_bonuses=_require_governor_store().bonuses(),
                research_bonuses=_require_research_store().bonuses(),
                gear=gear_pieces,
                troops_path=_current_troops_path(),
                active_marches=2,
                floor=int(stage_n) if use_stage_round else None,
                enemy_ratio=ratio_override if use_stage_round else None,
                enemy_bonuses=bonuses_override if use_stage_round else None,
                saved_opponents=saved_opponents if use_stage_round else None,
                player_report_bonuses=(
                    player_report_bonuses if use_stage_round else None
                ),
                player_event_troops=(
                    player_event_troops if use_stage_round else None
                ),
            )
            if use_stage_round:
                apply_saved_radiant_opponents(
                    payload,
                    governor_dir=gov_dir,
                    stage=int(stage_n),
                    round_no=int(round_n),
                )
            else:
                # Spec: blank stage or round → proxy only (hide opponent panel).
                payload.pop("opponent", None)
        except (ValueError, OSError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        eff_gear_dir = _current_gear_dir()
        try:
            if gear_pieces and eff_gear_dir is not None:
                bust = inventory_revision(eff_gear_dir, "gear.json")
                raw_icons = ensure_all_icons(gear_pieces, eff_gear_dir)
                attach_mystic_gear_icon_urls(
                    payload,
                    {
                        pid: with_cache_bust(url, bust)
                        for pid, url in raw_icons.items()
                    },
                )
        except Exception:  # noqa: BLE001
            pass
        try:
            bust_h = inventory_revision(heroes_path, "heroes.json")
            icon_map = ensure_all_hero_icons(heroes, heroes_path)
            icon_by_name = {
                name: with_cache_bust(url, bust_h) for name, url in icon_map.items()
            }
            for march in payload.get("marches") or []:
                if not isinstance(march, dict):
                    continue
                rows = list(march.get("heroes") or [])
                if not rows:
                    rows = [{"name": n} for n in (march.get("hero_names") or [])]
                for row in rows:
                    name = row.get("name")
                    if name and name in icon_by_name:
                        row["icon_url"] = icon_by_name[name]
                march["heroes"] = rows
        except Exception:  # noqa: BLE001
            pass
        payload["heroes_dir"] = str(heroes_path)
        payload["governor_dir"] = str(_current_governor_dir())
        payload["research_dir"] = str(_current_research_dir())
        return payload

    @app.put("/api/mystic-trial/radiant-opponents/{stage}/{round_no}/{slot}")
    def api_put_radiant_opponent(
        stage: int,
        round_no: int,
        slot: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one opponent march slot for a stage · round (Apply)."""
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            empty_march,
            get_stage_round,
            load_store,
            opponents_path,
            parse_march,
            save_store,
            upsert_march,
        )

        if stage < 1 or round_no < 1:
            raise HTTPException(
                status_code=400, detail="stage and round must be >= 1"
            )
        if slot not in (0, 1):
            raise HTTPException(status_code=400, detail="slot must be 0 or 1")
        try:
            march = parse_march(body)
            path = opponents_path(_current_governor_dir())
            store = upsert_march(
                load_store(path),
                stage=stage,
                round_no=round_no,
                slot=slot,
                march=march,
            )
            save_store(path, store)
            marches = get_stage_round(store, stage, round_no)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if marches is None:
            marches = [empty_march(), empty_march()]
        return {
            "stage": stage,
            "round": round_no,
            "slot": slot,
            "marches": marches,
            "path": str(path),
        }

    @app.get("/api/mystic-trial/radiant-opponents/{stage}/{round_no}")
    def api_get_radiant_opponents(stage: int, round_no: int) -> dict[str, Any]:
        """Load saved opponent overrides for a stage · round (no optimize)."""
        from ks.heroes.optimize.catalog import heroes_by_troop, load_catalog
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            empty_march,
            get_stage_round,
            load_store,
            opponents_path,
        )

        if stage < 1 or round_no < 1:
            raise HTTPException(
                status_code=400, detail="stage and round must be >= 1"
            )
        path = opponents_path(_current_governor_dir())
        store = load_store(path)
        marches = get_stage_round(store, stage, round_no)
        if marches is None:
            marches = [empty_march(), empty_march()]
        catalog = load_catalog(None, REPO_ROOT / "config" / "hero_catalog.yaml")
        roster_troop: dict[str, str] = {}
        eff_hero_store = _current_hero_store()
        if eff_hero_store is not None:
            roster_troop = {
                h.name: h.troop_type or ""
                for h in eff_hero_store.all_heroes()
                if h.name
            }
        from ks.heroes.ui.optimize_run import resolve_mystic_player_event_troops

        return {
            "stage": stage,
            "round": round_no,
            "marches": marches,
            "player_event_troops": resolve_mystic_player_event_troops(
                governor_dir=_current_governor_dir(),
                stage=stage,
                round_no=round_no,
                room="radiant",
                room_path=REPO_ROOT
                / "config"
                / "mystic_trial"
                / "radiant_spire.yaml",
            ),
            "catalog_hero_names": sorted(catalog.keys()),
            "catalog_by_troop": heroes_by_troop(
                catalog, roster_troop=roster_troop
            ),
            "path": str(path),
        }

    @app.put("/api/mystic-trial/radiant-event-troops/{stage}/{round_no}")
    def api_put_radiant_event_troops(
        stage: int,
        round_no: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist event-borrowed troop tier + march size for a stage·round."""
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            get_player_event_troops,
            load_store,
            opponents_path,
            parse_player_event_troops,
            save_store,
            upsert_player_event_troops,
        )

        if stage < 1 or round_no < 1:
            raise HTTPException(
                status_code=400, detail="stage and round must be >= 1"
            )
        try:
            event_troops = parse_player_event_troops(body)
            path = opponents_path(_current_governor_dir(), room="radiant")
            store = upsert_player_event_troops(
                load_store(path),
                stage=stage,
                round_no=round_no,
                event_troops=event_troops,
            )
            save_store(path, store)
            saved = get_player_event_troops(store, stage, round_no)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "stage": stage,
            "round": round_no,
            "player_event_troops": saved,
            "path": str(path),
        }

    @app.put("/api/mystic-trial/radiant-player-bonuses/{stage}/{round_no}")
    def api_put_radiant_player_bonuses(
        stage: int,
        round_no: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist your battle-report formation Atk/Def/Leth/HP for a stage·round."""
        from ks.heroes.optimize.mystic_trial.floors import parse_enemy_bonuses
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            get_player_bonuses,
            load_store,
            opponents_path,
            save_store,
            upsert_player_bonuses,
        )

        if stage < 1 or round_no < 1:
            raise HTTPException(
                status_code=400, detail="stage and round must be >= 1"
            )
        try:
            bonuses = parse_enemy_bonuses(body.get("bonuses", body))
            path = opponents_path(_current_governor_dir())
            store = upsert_player_bonuses(
                load_store(path),
                stage=stage,
                round_no=round_no,
                bonuses=bonuses,
            )
            save_store(path, store)
            saved = get_player_bonuses(store, stage, round_no)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "stage": stage,
            "round": round_no,
            "player_bonuses": saved,
            "path": str(path),
        }

    @app.get("/api/optimize/coliseum")
    def api_optimize_coliseum(
        stage: int | None = None,
        round: int | None = None,
    ) -> dict[str, Any]:
        """Dual-march Coliseum proxy — heroes + gear; governor weight 0.

        Pass both ``stage`` and ``round`` for opponent overrides (same UX as
        Radiant Spire). Without both, proxy-only with no opponent panel.
        """
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            empty_march,
            get_stage_round,
            load_store,
            opponents_path,
        )
        from ks.heroes.ui.optimize_run import (
            apply_saved_radiant_opponents,
            attach_mystic_gear_icon_urls,
            resolve_mystic_player_event_troops,
            run_coliseum_optimize,
        )

        heroes_path, hero_store_local = _require_heroes()
        hero_store_local.reload()
        heroes = hero_store_local.all_heroes()
        gear_pieces: list[GearRecord] = []
        eff_gear_store = _current_gear_store()
        if eff_gear_store is not None:
            eff_gear_store.reload()
            gear_pieces = eff_gear_store.all_pieces()

        use_stage_round = stage is not None and round is not None
        gov_dir = _current_governor_dir()
        try:
            saved_opponents = None
            player_event_troops = None
            if use_stage_round:
                store = load_store(
                    opponents_path(gov_dir, room="coliseum")
                )
                saved_opponents = get_stage_round(
                    store, int(stage), int(round)
                )
                player_event_troops = resolve_mystic_player_event_troops(
                    governor_dir=gov_dir,
                    stage=int(stage),
                    round_no=int(round),
                    room="coliseum",
                    room_path=REPO_ROOT
                    / "config"
                    / "mystic_trial"
                    / "coliseum.yaml",
                )
            else:
                # Room defaults (event-borrowed) even without stage·round.
                from ks.heroes.optimize.mystic_trial.radiant_opponents import (
                    default_player_event_troops,
                )
                from ks.heroes.optimize.mystic_trial.rooms import load_room

                room_cfg = load_room(
                    REPO_ROOT / "config" / "mystic_trial" / "coliseum.yaml"
                )
                player_event_troops = default_player_event_troops(
                    tier=room_cfg.event_troop_tier,
                    march_size=room_cfg.event_march_capacity,
                )
            payload = run_coliseum_optimize(
                heroes,
                governor_bonuses=_require_governor_store().bonuses(),
                gear=gear_pieces,
                troops_path=_current_troops_path(),
                saved_opponents=saved_opponents if use_stage_round else None,
                player_event_troops=player_event_troops,
            )
            if use_stage_round:
                apply_saved_radiant_opponents(
                    payload,
                    governor_dir=gov_dir,
                    stage=int(stage),
                    round_no=int(round),
                    room="coliseum",
                )
                # No floor stub → ensure Opponent 1/2 chips even with empty save.
                if not payload.get("opponent"):
                    payload["opponent"] = {
                        "saved": False,
                        "marches": [empty_march(), empty_march()],
                    }
            else:
                payload.pop("opponent", None)
        except (ValueError, OSError, FileNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        eff_gear_dir = _current_gear_dir()
        try:
            if gear_pieces and eff_gear_dir is not None:
                bust = inventory_revision(eff_gear_dir, "gear.json")
                raw_icons = ensure_all_icons(gear_pieces, eff_gear_dir)
                attach_mystic_gear_icon_urls(
                    payload,
                    {
                        pid: with_cache_bust(url, bust)
                        for pid, url in raw_icons.items()
                    },
                )
        except Exception:  # noqa: BLE001
            pass
        try:
            bust_h = inventory_revision(heroes_path, "heroes.json")
            icon_map = ensure_all_hero_icons(heroes, heroes_path)
            icon_by_name = {
                name: with_cache_bust(url, bust_h) for name, url in icon_map.items()
            }
            for march in payload.get("marches") or []:
                if not isinstance(march, dict):
                    continue
                rows = list(march.get("heroes") or [])
                if not rows:
                    rows = [{"name": n} for n in (march.get("hero_names") or [])]
                for row in rows:
                    name = row.get("name")
                    if name and name in icon_by_name:
                        row["icon_url"] = icon_by_name[name]
                march["heroes"] = rows
        except Exception:  # noqa: BLE001
            pass
        payload["heroes_dir"] = str(heroes_path)
        payload["governor_dir"] = str(gov_dir)
        return payload

    @app.put("/api/mystic-trial/coliseum-opponents/{stage}/{round_no}/{slot}")
    def api_put_coliseum_opponent(
        stage: int,
        round_no: int,
        slot: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one Coliseum opponent march slot for a stage · round."""
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            empty_march,
            get_stage_round,
            load_store,
            opponents_path,
            parse_march,
            save_store,
            upsert_march,
        )

        if stage < 1 or round_no < 1:
            raise HTTPException(
                status_code=400, detail="stage and round must be >= 1"
            )
        if slot not in (0, 1):
            raise HTTPException(status_code=400, detail="slot must be 0 or 1")
        try:
            march = parse_march(body)
            path = opponents_path(_current_governor_dir(), room="coliseum")
            store = upsert_march(
                load_store(path),
                stage=stage,
                round_no=round_no,
                slot=slot,
                march=march,
            )
            save_store(path, store)
            marches = get_stage_round(store, stage, round_no)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if marches is None:
            marches = [empty_march(), empty_march()]
        return {
            "stage": stage,
            "round": round_no,
            "slot": slot,
            "marches": marches,
            "path": str(path),
        }

    @app.get("/api/mystic-trial/coliseum-opponents/{stage}/{round_no}")
    def api_get_coliseum_opponents(stage: int, round_no: int) -> dict[str, Any]:
        """Load saved Coliseum opponent overrides for a stage · round."""
        from ks.heroes.optimize.catalog import heroes_by_troop, load_catalog
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            empty_march,
            get_stage_round,
            load_store,
            opponents_path,
        )

        if stage < 1 or round_no < 1:
            raise HTTPException(
                status_code=400, detail="stage and round must be >= 1"
            )
        path = opponents_path(_current_governor_dir(), room="coliseum")
        store = load_store(path)
        marches = get_stage_round(store, stage, round_no)
        if marches is None:
            marches = [empty_march(), empty_march()]
        catalog = load_catalog(None, REPO_ROOT / "config" / "hero_catalog.yaml")
        roster_troop: dict[str, str] = {}
        eff_hero_store = _current_hero_store()
        if eff_hero_store is not None:
            roster_troop = {
                h.name: h.troop_type or ""
                for h in eff_hero_store.all_heroes()
                if h.name
            }
        from ks.heroes.ui.optimize_run import resolve_mystic_player_event_troops

        return {
            "stage": stage,
            "round": round_no,
            "marches": marches,
            "player_event_troops": resolve_mystic_player_event_troops(
                governor_dir=_current_governor_dir(),
                stage=stage,
                round_no=round_no,
                room="coliseum",
                room_path=REPO_ROOT / "config" / "mystic_trial" / "coliseum.yaml",
            ),
            "catalog_hero_names": sorted(catalog.keys()),
            "catalog_by_troop": heroes_by_troop(
                catalog, roster_troop=roster_troop
            ),
            "path": str(path),
        }

    @app.put("/api/mystic-trial/coliseum-event-troops/{stage}/{round_no}")
    def api_put_coliseum_event_troops(
        stage: int,
        round_no: int,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist Coliseum event-borrowed troop tier + march size."""
        from ks.heroes.optimize.mystic_trial.radiant_opponents import (
            get_player_event_troops,
            load_store,
            opponents_path,
            parse_player_event_troops,
            save_store,
            upsert_player_event_troops,
        )

        if stage < 1 or round_no < 1:
            raise HTTPException(
                status_code=400, detail="stage and round must be >= 1"
            )
        try:
            event_troops = parse_player_event_troops(body)
            path = opponents_path(_current_governor_dir(), room="coliseum")
            store = upsert_player_event_troops(
                load_store(path),
                stage=stage,
                round_no=round_no,
                event_troops=event_troops,
            )
            save_store(path, store)
            saved = get_player_event_troops(store, stage, round_no)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "stage": stage,
            "round": round_no,
            "player_event_troops": saved,
            "path": str(path),
        }

    @app.get("/api/optimize/molten-fort")
    def api_optimize_molten() -> dict[str, Any]:
        """Single-march Molten Fort proxy — governor-primary scoring."""
        heroes_path, hero_store_local = _require_heroes()
        from ks.heroes.ui.optimize_run import (
            attach_mystic_gear_icon_urls,
            run_molten_optimize,
        )

        hero_store_local.reload()
        heroes = hero_store_local.all_heroes()
        gear_pieces: list[GearRecord] = []
        eff_gear_store = _current_gear_store()
        if eff_gear_store is not None:
            eff_gear_store.reload()
            gear_pieces = eff_gear_store.all_pieces()
        try:
            payload = run_molten_optimize(
                heroes,
                governor_bonuses=_require_governor_store().bonuses(),
                gear=gear_pieces,
                troops_path=_current_troops_path(),
            )
        except (ValueError, OSError, FileNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        eff_gear_dir = _current_gear_dir()
        try:
            if gear_pieces and eff_gear_dir is not None:
                bust = inventory_revision(eff_gear_dir, "gear.json")
                raw_icons = ensure_all_icons(gear_pieces, eff_gear_dir)
                attach_mystic_gear_icon_urls(
                    payload,
                    {
                        pid: with_cache_bust(url, bust)
                        for pid, url in raw_icons.items()
                    },
                )
        except Exception:  # noqa: BLE001
            pass
        payload["heroes_dir"] = str(heroes_path)
        payload["governor_dir"] = str(_current_governor_dir())
        return payload

    def _prepare_gear_xp_search(body: dict[str, Any]) -> tuple[str, Any, list[GearRecord], Any]:
        """Shared request parsing for the blocking and streaming gear-XP
        endpoints: validates fodder counts, resolves the roster/gear/troops
        the body asks for, and builds the utility function the search will
        call. Raises HTTPException for anything the client sent wrong."""
        heroes_path, hero_store_local = _require_heroes()
        eff_gear_store = _current_gear_store()
        eff_gear_dir = _current_gear_dir()
        if eff_gear_store is None or eff_gear_dir is None:
            raise HTTPException(
                status_code=400,
                detail="gear inventory required; start UI with --gear",
            )
        from ks.heroes.optimize.spend_xp import build_event_utility
        from ks.heroes.optimize.xp_ladder import FodderBag

        event = str(body.get("event") or "swordland").strip().lower()
        mode = body.get("mode")
        mode_s = str(mode).strip() if mode else None

        def _count(key: str) -> int:
            raw = body.get(key, 0)
            try:
                n = int(raw)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"invalid fodder count for {key}"
                ) from exc
            if n < 0:
                raise HTTPException(
                    status_code=400, detail=f"{key} must be non-negative"
                )
            return n

        bag = FodderBag(
            grey=_count("grey"),
            green=_count("green"),
            blue=_count("blue"),
            purple=_count("purple"),
            part_100=_count("part_100"),
        )
        hero_store_local.reload()
        heroes = hero_store_local.all_heroes()
        eff_gear_store.reload()
        gear_pieces = eff_gear_store.all_pieces()
        if not gear_pieces:
            raise HTTPException(status_code=400, detail="gear inventory is empty")
        try:
            utility_fn = build_event_utility(
                event, heroes, mode=mode_s, troops_path=_current_troops_path()
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return event, bag, gear_pieces, utility_fn

    @app.post("/api/optimize/gear-xp")
    def api_optimize_gear_xp(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Allocate fodder XP to maximize event utility (propose only)."""
        from ks.heroes.optimize.spend_xp import allocate_fodder_xp

        event, bag, gear_pieces, utility_fn = _prepare_gear_xp_search(body)
        try:
            result = allocate_fodder_xp(gear_pieces, bag, utility_fn, event=event)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    @app.post("/api/optimize/gear-xp/stream")
    def api_optimize_gear_xp_stream(body: dict[str, Any] = Body(...)) -> Any:
        """Same search as /api/optimize/gear-xp, streamed as newline-delimited
        JSON progress events instead of one blocking reply — see
        ks.heroes.optimize.spend_xp.iter_allocate_fodder_xp for the event
        shapes. The plain endpoint's response contract is untouched for any
        other consumer; only the interactive planner page uses this one, so
        a search that can take minutes shows real per-step progress instead
        of a silent wait.

        Request validation (bad counts, missing gear, unsupported event)
        still happens before the stream opens and still reports as a normal
        4xx — only a failure discovered *during* the search (an infeasible
        baseline) has already committed to a 200 response and is reported as
        an in-stream ``{"type": "error", "detail": ...}`` line instead.
        """
        import json

        from ks.heroes.optimize.spend_xp import iter_allocate_fodder_xp

        event, bag, gear_pieces, utility_fn = _prepare_gear_xp_search(body)

        def _events() -> Any:
            try:
                for ev in iter_allocate_fodder_xp(
                    gear_pieces, bag, utility_fn, event=event
                ):
                    if ev["type"] == "done":
                        ev = {**ev, "result": ev["result"].to_dict()}
                    yield json.dumps(ev) + "\n"
            except ValueError as exc:
                yield json.dumps({"type": "error", "detail": str(exc)}) + "\n"

        return StreamingResponse(_events(), media_type="application/x-ndjson")

    if auth_config is not None:
        from ks.auth.middleware import install_auth

        install_auth(
            app,
            auth_config,
            users_root,
            troops_seed=REPO_ROOT / "config" / "troops.yaml",
            http_client_factory=http_client_factory,
        )

    return app


def run_ui(
    gear_dir: Path | None = None,
    *,
    heroes_dir: Path | None = None,
    troops_path: Path | None = None,
    governor_dir: Path | None = None,
    research_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    gear_config: Path | None = None,
    heroes_config: Path | None = None,
    serial: str | None = None,
) -> None:
    """Serve the Inventory/Optimiser UI (blocking)."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "UI dependencies missing; install with: pip install 'ks[ui]'"
        ) from exc

    app = create_app(
        gear_dir,
        heroes_dir=heroes_dir,
        troops_path=troops_path,
        governor_dir=governor_dir,
        research_dir=research_dir,
        gear_config=gear_config,
        heroes_config=heroes_config,
        serial=serial,
    )
    for label, path in startup_paths(
        gear=gear_dir is not None, heroes=heroes_dir is not None
    ):
        print(f"{label}: http://{host}:{port}{path}")
    if heroes_dir is not None:
        print(f"Heroes: {Path(heroes_dir).expanduser().resolve()}")
    if gear_dir is not None:
        print(f"Gear: {Path(gear_dir).expanduser().resolve()}")
    print(f"Troops: {app.state.troops_path}")
    print(f"Governor: {app.state.governor_dir}")
    print(f"Research: {app.state.research_dir}")
    uvicorn.run(app, host=host, port=port, log_level="info")
