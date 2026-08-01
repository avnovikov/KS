"""FastAPI app: gear inventory view + level edits via GearStore."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_store import GearStore
from ks.heroes.ui.icons import ensure_all_icons
from ks.heroes.ui.power import compute_gear_power

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError:  # pragma: no cover - exercised when ui extras missing
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


def sync_piece_power(piece: GearRecord) -> GearRecord:
    """Return piece with power derived from rarity/enhancement/mastery."""
    if piece.enhancement_level is None and piece.rarity is None:
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


def create_app(gear_dir: Path) -> Any:
    """Build FastAPI app bound to a gear inventory directory."""
    if FastAPI is None:
        raise ImportError(
            "UI dependencies missing; install with: pip install 'ks[ui]'"
        )

    resolved = _resolve_gear_dir(gear_dir)
    store = GearStore(resolved)
    sync_all_powers(store)
    icons = ensure_all_icons(store.all_pieces(), resolved)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app = FastAPI(title="KS Heroes Gear UI", version="0.1.0")
    app.state.gear_dir = resolved
    app.state.store = store
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    icons_path = resolved / "icons"
    icons_path.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/icons",
        StaticFiles(directory=str(icons_path)),
        name="icons",
    )

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(url="/gear", status_code=302)

    @app.get("/gear", response_class=HTMLResponse)
    def gear_page(request: Request) -> HTMLResponse:
        pieces = store.all_pieces()
        icon_map = ensure_all_icons(pieces, resolved)
        return templates.TemplateResponse(
            request,
            "gear.html",
            {
                "pieces": pieces,
                "icons": icon_map,
                "gear_dir": str(resolved),
            },
        )

    @app.get("/api/gear")
    def api_list_gear() -> dict[str, Any]:
        pieces = store.all_pieces()
        icon_map = ensure_all_icons(pieces, resolved)
        return {
            "gear": [
                {**p.to_dict(), "icon_url": icon_map.get(p.piece_id)}
                for p in pieces
            ]
        }

    @app.patch("/api/gear/{piece_id}")
    async def api_patch_gear(piece_id: str, request: Request) -> dict[str, Any]:
        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON body required") from exc
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="JSON object required")

        enh_arg: Any = ...
        mast_arg: Any = ...
        if "enhancement_level" in raw:
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
        icon_url = ensure_all_icons([updated], resolved).get(piece_id)
        return {
            "ok": True,
            "piece": {**updated.to_dict(), "icon_url": icon_url},
        }

    return app


def run_ui(gear_dir: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the gear UI (blocking)."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "UI dependencies missing; install with: pip install 'ks[ui]'"
        ) from exc

    app = create_app(gear_dir)
    print(f"Gear UI: http://{host}:{port}/gear")
    print(f"Inventory: {Path(gear_dir).expanduser().resolve()}")
    uvicorn.run(app, host=host, port=port, log_level="info")
