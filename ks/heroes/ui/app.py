"""FastAPI app: gear inventory view + level edits via GearStore."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ks.heroes.gear_models import GearRecord
from ks.heroes.gear_store import GearStore

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
except ImportError:  # pragma: no cover - exercised when ui extras missing
    FastAPI = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    HTMLResponse = None  # type: ignore[assignment,misc]
    RedirectResponse = None  # type: ignore[assignment,misc]
    Jinja2Templates = None  # type: ignore[assignment,misc]


def _resolve_gear_dir(gear: Path) -> Path:
    path = gear.expanduser().resolve()
    if path.is_file() and path.name == "gear.json":
        return path.parent
    if path.is_dir():
        return path
    raise FileNotFoundError(f"gear path not found: {gear}")


def update_piece_levels(
    store: GearStore,
    piece_id: str,
    *,
    enhancement_level: int | None | object = ...,
    mastery_level: int | None | object = ...,
) -> GearRecord:
    """Update enhancement and/or mastery on one piece; persist JSON + DB."""
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
    store.upsert(updated)
    return updated


def create_app(gear_dir: Path) -> Any:
    """Build FastAPI app bound to a gear inventory directory."""
    if FastAPI is None:
        raise ImportError(
            "UI dependencies missing; install with: pip install 'ks[ui]'"
        )

    resolved = _resolve_gear_dir(gear_dir)
    store = GearStore(resolved)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app = FastAPI(title="KS Heroes Gear UI", version="0.1.0")
    app.state.gear_dir = resolved
    app.state.store = store

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(url="/gear", status_code=302)

    @app.get("/gear", response_class=HTMLResponse)
    def gear_page(request: Request) -> HTMLResponse:
        pieces = store.all_pieces()
        return templates.TemplateResponse(
            request,
            "gear.html",
            {
                "pieces": pieces,
                "gear_dir": str(resolved),
            },
        )

    @app.get("/api/gear")
    def api_list_gear() -> dict[str, Any]:
        return {"gear": [p.to_dict() for p in store.all_pieces()]}

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
        return {"ok": True, "piece": updated.to_dict()}

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
