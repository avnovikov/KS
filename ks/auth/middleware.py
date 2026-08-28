"""Auth middleware: protect routes and bind per-user inventory.

Public paths (no auth check): /auth/* and /static/*.
/api/* without session → 401 JSON.
All other paths without session → 302 /auth/login.

When auth is on and the user is authenticated the middleware:
  1. Sets ``request.state.user`` from the session.
  2. Calls ``build_inventory_bundle`` for that user's paths.
  3. Binds the bundle on ``request.state.inventory`` *and* on a ContextVar so
     that sync route handlers (which run in a thread pool) also pick it up via
     ``get_current_inventory()``.
  4. Resets the ContextVar after ``call_next`` returns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx

from ks.auth.config import AuthConfig
from ks.auth.routes import build_auth_router
from ks.auth.session_user import get_session_user

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, RedirectResponse
except ImportError:  # pragma: no cover
    BaseHTTPMiddleware = object  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    JSONResponse = None  # type: ignore[assignment,misc]
    RedirectResponse = None  # type: ignore[assignment,misc]


class ProtectRoutesMiddleware(BaseHTTPMiddleware):
    """Block unauthenticated requests; bind per-user inventory when authed.

    HTML pages → 302 /auth/login.
    /api/* → 401 JSON {"detail": "unauthorized"}.
    /auth/* and /static/* are always public.
    """

    async def dispatch(self, request: "Request", call_next: Callable) -> object:
        path = request.url.path
        if self._is_public(path):
            return await call_next(request)

        user = get_session_user(request.session)
        if user is not None:
            request.state.user = user
            users_root: Path | None = getattr(request.app.state, "users_root", None)
            troops_seed: Path | None = getattr(request.app.state, "troops_seed", None)
            if users_root is not None and troops_seed is not None:
                return await self._dispatch_with_inventory(
                    request, call_next, user, users_root, troops_seed
                )
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return RedirectResponse(url="/auth/login", status_code=302)

    async def _dispatch_with_inventory(
        self,
        request: "Request",
        call_next: Callable,
        user: object,
        users_root: Path,
        troops_seed: Path,
    ) -> object:
        """Build per-user inventory, bind it, call handler, then clean up."""
        from ks.auth.inventory import paths_for
        from ks.auth.request_inventory import (
            _REQUEST_INVENTORY,
            build_inventory_bundle,
        )

        paths = paths_for(users_root, user.id)  # type: ignore[attr-defined]
        bundle = build_inventory_bundle(paths, troops_seed=troops_seed)
        request.state.inventory = bundle
        token = _REQUEST_INVENTORY.set(bundle)
        try:
            return await call_next(request)
        finally:
            _REQUEST_INVENTORY.reset(token)

    @staticmethod
    def _is_public(path: str) -> bool:
        return path == "/auth" or path.startswith("/auth/") or path.startswith("/static/")


def install_auth(
    app: object,
    cfg: AuthConfig,
    users_root: Path | None,
    *,
    troops_seed: Path | None = None,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> None:
    """Attach SessionMiddleware, ProtectRoutesMiddleware, and auth router.

    Middleware must be added in the right order so SessionMiddleware
    (outer) populates ``request.session`` before ProtectRoutesMiddleware
    (inner) reads it.  FastAPI processes the last ``add_middleware`` call
    outermost.
    """
    from starlette.middleware.sessions import SessionMiddleware

    # https_only=True secures the session cookie over HTTPS; keep False for
    # local/dev so TestClient and plain http:// UIs still work.
    https_only = cfg.public_base_url.startswith("https://")

    # Inner → runs second on request (after session is available)
    app.add_middleware(ProtectRoutesMiddleware)  # type: ignore[union-attr]
    # Outer → runs first on request, populates request.session
    app.add_middleware(  # type: ignore[union-attr]
        SessionMiddleware,
        secret_key=cfg.session_secret,
        https_only=https_only,
    )

    auth_router = build_auth_router(cfg, http_client_factory=http_client_factory)
    app.include_router(auth_router)  # type: ignore[union-attr]

    app.state.auth_config = cfg  # type: ignore[union-attr]
    app.state.users_root = users_root  # type: ignore[union-attr]
    app.state.troops_seed = troops_seed  # type: ignore[union-attr]
