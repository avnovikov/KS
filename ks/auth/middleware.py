"""Auth middleware: protect routes and bind session user.

Public paths (no auth check): /auth/* and /static/*.
/api/* without session → 401 JSON.
All other paths without session → 302 /auth/login.
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

_PUBLIC_PREFIXES = ("/auth/", "/static/", "/auth")


class ProtectRoutesMiddleware(BaseHTTPMiddleware):
    """Block unauthenticated requests.

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
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return RedirectResponse(url="/auth/login", status_code=302)

    @staticmethod
    def _is_public(path: str) -> bool:
        return path == "/auth" or path.startswith("/auth/") or path.startswith("/static/")


def install_auth(
    app: object,
    cfg: AuthConfig,
    users_root: Path | None,
    *,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> None:
    """Attach SessionMiddleware, ProtectRoutesMiddleware, and auth router.

    Middleware must be added in the right order so SessionMiddleware
    (outer) populates ``request.session`` before ProtectRoutesMiddleware
    (inner) reads it.  FastAPI processes the last ``add_middleware`` call
    outermost.
    """
    from starlette.middleware.sessions import SessionMiddleware

    # Inner → runs second on request (after session is available)
    app.add_middleware(ProtectRoutesMiddleware)  # type: ignore[union-attr]
    # Outer → runs first on request, populates request.session
    app.add_middleware(SessionMiddleware, secret_key=cfg.session_secret)  # type: ignore[union-attr]

    auth_router = build_auth_router(cfg, http_client_factory=http_client_factory)
    app.include_router(auth_router)  # type: ignore[union-attr]

    app.state.auth_config = cfg  # type: ignore[union-attr]
    app.state.users_root = users_root  # type: ignore[union-attr]
