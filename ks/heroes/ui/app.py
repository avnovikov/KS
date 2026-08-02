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

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STARS_RANGE = range(0, 6)
_PELLETS_RANGE = range(0, 6)


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
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError:  # pragma: no cover - exercised when ui extras missing
    Body = None  # type: ignore[assignment,misc]
    FastAPI = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    HTMLResponse = None  # type: ignore[assignment,misc]
    RedirectResponse = None  # type: ignore[assignment,misc]
    StaticFiles = None  # type: ignore[assignment,misc]
    Jinja2Templates = None  # type: ignore[assignment,misc]


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


def update_piece_levels(
    store: GearStore,
    piece_id: str,
    *,
    enhancement_level: int | None | object = ...,
    mastery_level: int | None | object = ...,
) -> GearRecord:
    """Update enhancement and/or mastery; recompute power; persist JSON + DB."""
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

    if not updates:
        return piece
    updated = replace(piece, **updates)
    updated = sync_piece_power(updated)
    store.upsert(updated)
    return updated


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
) -> HeroRecord:
    """Update stars/pellets; rescale naked power via star_progress_factor."""
    heroes = {h.name: h for h in store.all_heroes()}
    hero = heroes.get(name)
    if hero is None:
        raise KeyError(name)

    new_stars = hero.stars
    new_pellets = hero.pellets
    if stars is not ...:
        if stars is not None:
            level = int(stars)
            if level not in _STARS_RANGE:
                raise ValueError(f"stars must be 0..5; got {level}")
            new_stars = level
        else:
            new_stars = None
    if pellets is not ...:
        if pellets is not None:
            level = int(pellets)
            if level not in _PELLETS_RANGE:
                raise ValueError(f"pellets must be 0..5; got {level}")
            new_pellets = level
        else:
            new_pellets = None

    if new_stars == hero.stars and new_pellets == hero.pellets:
        return hero

    new_power = scale_power_for_star_change(
        hero.power,
        hero.stars,
        hero.pellets,
        new_stars,
        new_pellets,
    )
    updated = replace(
        hero, stars=new_stars, pellets=new_pellets, power=new_power
    )
    store.upsert(updated)
    return updated


def create_app(
    gear_dir: Path | None = None,
    *,
    heroes_dir: Path | None = None,
    gear_config: Path | None = None,
    heroes_config: Path | None = None,
    serial: str | None = None,
    rescan_fn: Callable[..., list[GearRecord]] | None = None,
    heroes_rescan_fn: Callable[..., list[HeroRecord]] | None = None,
) -> Any:
    """Build FastAPI app bound to gear and/or heroes inventory directories."""
    if FastAPI is None:
        raise ImportError(
            "UI dependencies missing; install with: pip install 'ks[ui]'"
        )
    if gear_dir is None and heroes_dir is None:
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
    # gear. One of the two is always set (checked above), so this is never
    # None; /inventory/troops and /api/troops stay ungated for the same
    # reason.
    troops_dir = resolved_heroes if resolved_heroes is not None else resolved_gear
    troop_store = TroopStore(
        troops_dir / "troops.yaml",
        seed_from=REPO_ROOT / "config" / "troops.yaml",
    )
    troop_store.ensure_exists()
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
    app.state.store = gear_store
    app.state.hero_store = hero_store
    app.state.gear_config = gear_config_path
    app.state.heroes_config = heroes_config_path
    app.state.serial = serial
    app.state.troops_path = troop_store.path
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

    def _require_gear() -> tuple[Path, GearStore]:
        if resolved_gear is None or gear_store is None:
            raise HTTPException(status_code=404, detail="gear UI not configured")
        return resolved_gear, gear_store

    def _require_heroes() -> tuple[Path, HeroStore]:
        if resolved_heroes is None or hero_store is None:
            raise HTTPException(
                status_code=404, detail="heroes UI not configured"
            )
        return resolved_heroes, hero_store

    def _shell_page(
        request: Request,
        template: str,
        *,
        primary: str,
        subtab: str,
        **extra: Any,
    ) -> HTMLResponse:
        """Render a page inside the Inventory/Optimiser shell (never cached)."""
        context: dict[str, Any] = {
            "primary": primary,
            "subtab": subtab,
            "gear_enabled": resolved_gear is not None,
            "heroes_enabled": resolved_heroes is not None,
        }
        context.update(extra)
        response = templates.TemplateResponse(request, template, context)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        if resolved_gear is not None:
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
        raw: dict[str, Any] = {}
        load_error: str | None = None
        try:
            raw = troop_store.load_raw()
            _troop_totals(raw)
        except (yaml.YAMLError, ValueError, TypeError) as exc:
            load_error = str(exc)
        return _shell_page(
            request,
            "inventory_troops.html",
            primary="inventory",
            subtab="troops",
            form=troops_form_model(raw),
            troops_path=str(troop_store.path),
            load_error=load_error,
        )

    @app.get("/optimiser/events", response_class=HTMLResponse)
    def optimiser_events_page(request: Request) -> HTMLResponse:
        _require_heroes()
        return _shell_page(
            request,
            "optimiser_events.html",
            primary="optimiser",
            subtab="events",
        )

    @app.get("/optimiser/gear-xp", response_class=HTMLResponse)
    def optimiser_gear_xp_page(request: Request) -> HTMLResponse:
        _require_heroes()
        return _shell_page(
            request,
            "optimiser_gear_xp.html",
            primary="optimiser",
            subtab="gear-xp",
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
        return {
            "ok": True,
            "count": len(pieces),
            "cache_bust": bust,
            "gear": [
                {
                    **p.to_dict(),
                    "icon_url": with_cache_bust(icon_map.get(p.piece_id), bust),
                }
                for p in pieces
            ],
        }

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
        if raw.get("clear_enhancement"):
            enh_arg = None
        elif "enhancement_level" in raw:
            enh_arg = raw.get("enhancement_level")
        if raw.get("clear_mastery"):
            mast_arg = None
        elif "mastery_level" in raw:
            mast_arg = raw.get("mastery_level")

        try:
            updated = update_piece_levels(
                store,
                piece_id,
                enhancement_level=enh_arg,
                mastery_level=mast_arg,
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
        return {"hero": {**hero.to_dict(), "icon_url": icon_url}}

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
        if "stars" in raw:
            stars_arg = raw.get("stars")
        if "pellets" in raw:
            pellets_arg = raw.get("pellets")

        try:
            updated = update_hero_stars(
                store,
                name,
                stars=stars_arg,
                pellets=pellets_arg,
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
        return {
            "ok": True,
            "count": len(heroes),
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
        try:
            raw = troop_store.load_raw()
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
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        try:
            saved = troop_store.save_raw(raw)
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
        if gear_store is not None and resolved_gear is not None:
            gear_store.reload()
            gear_pieces = gear_store.all_pieces() or None
            if gear_pieces:
                try:
                    bust = inventory_revision(resolved_gear, "gear.json")
                    raw_icons = ensure_all_icons(gear_pieces, resolved_gear)
                    icon_by_id = {
                        pid: with_cache_bust(url, bust)
                        for pid, url in raw_icons.items()
                    }
                except Exception as exc:  # noqa: BLE001 — optimize without icons
                    icon_warning = f"gear icons unavailable: {exc}"
        bundle = run_optimize_bundle(
            heroes, gear=gear_pieces, troops_path=app.state.troops_path
        )
        if icon_by_id:
            attach_gear_icon_urls(bundle, icon_by_id)
        if icon_warning:
            warnings = list(bundle.get("warnings") or [])
            warnings.append(icon_warning)
            bundle["warnings"] = warnings
        bundle["heroes_dir"] = str(heroes_path)
        return bundle

    @app.post("/api/optimize/gear-xp")
    def api_optimize_gear_xp(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Allocate fodder XP to maximize event utility (propose only)."""
        heroes_path, hero_store_local = _require_heroes()
        if gear_store is None or resolved_gear is None:
            raise HTTPException(
                status_code=400,
                detail="gear inventory required; start UI with --gear",
            )
        from ks.heroes.optimize.spend_xp import allocate_fodder_xp, build_event_utility
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
        gear_store.reload()
        gear_pieces = gear_store.all_pieces()
        if not gear_pieces:
            raise HTTPException(status_code=400, detail="gear inventory is empty")
        try:
            utility_fn = build_event_utility(
                event, heroes, mode=mode_s, troops_path=app.state.troops_path
            )
            result = allocate_fodder_xp(
                gear_pieces,
                bag,
                utility_fn,
                event=event,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    return app


def run_ui(
    gear_dir: Path | None = None,
    *,
    heroes_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    gear_config: Path | None = None,
    heroes_config: Path | None = None,
    serial: str | None = None,
) -> None:
    """Serve the gear/heroes/optimize UI (blocking)."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "UI dependencies missing; install with: pip install 'ks[ui]'"
        ) from exc

    app = create_app(
        gear_dir,
        heroes_dir=heroes_dir,
        gear_config=gear_config,
        heroes_config=heroes_config,
        serial=serial,
    )
    if heroes_dir is not None:
        print(f"Heroes UI: http://{host}:{port}/heroes")
        print(f"Optimize hub: http://{host}:{port}/optimize")
        print(f"Event lineups: http://{host}:{port}/optimize/events")
        print(f"Gear XP spend: http://{host}:{port}/optimize/gear-xp")
        print(f"Heroes: {Path(heroes_dir).expanduser().resolve()}")
    if gear_dir is not None:
        print(f"Gear UI: http://{host}:{port}/gear")
        print(f"Inventory: {Path(gear_dir).expanduser().resolve()}")
    uvicorn.run(app, host=host, port=port, log_level="info")
