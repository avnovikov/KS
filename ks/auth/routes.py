"""Discord OAuth routes: /auth/login, /auth/callback, /auth/logout."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Callable

import httpx

from ks.auth.config import AuthConfig
from ks.auth.discord_oauth import discord_authorize_url, exchange_code, fetch_discord_user
from ks.auth.gate import user_has_ui_access
from ks.auth.session_user import clear_session_user, set_session_user

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    HTMLResponse = None  # type: ignore[assignment,misc]
    RedirectResponse = None  # type: ignore[assignment,misc]
    Jinja2Templates = None  # type: ignore[assignment,misc]


_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "heroes" / "ui" / "templates"
_SESSION_STATE_KEY = "oauth_state"


def build_auth_router(
    cfg: AuthConfig,
    *,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> "APIRouter":
    """Create the /auth/* router.

    ``http_client_factory`` is a zero-arg callable that returns an
    ``httpx.AsyncClient``; defaults to the bare constructor.  Tests inject
    a factory that returns a transport-mocked client.
    """
    if APIRouter is None:  # pragma: no cover
        raise ImportError("FastAPI not installed; install ks[ui]")

    _client_factory = http_client_factory or httpx.AsyncClient
    router = APIRouter(prefix="/auth", tags=["auth"])
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @router.get("/login", response_class=HTMLResponse)
    async def login(request: Request) -> HTMLResponse:
        state = secrets.token_urlsafe(16)
        request.session[_SESSION_STATE_KEY] = state
        auth_url = discord_authorize_url(cfg, state)
        return templates.TemplateResponse(
            request, "login.html", {"auth_url": auth_url}
        )

    @router.get("/callback", response_model=None)
    async def callback(
        request: Request,
        code: str = "",
        state: str = "",
    ) -> "HTMLResponse | RedirectResponse":
        expected = request.session.get(_SESSION_STATE_KEY)
        if not expected or state != expected:
            return RedirectResponse(url="/auth/login?error=state", status_code=302)
        request.session.pop(_SESSION_STATE_KEY, None)

        async with _client_factory() as http:
            try:
                token_payload = await exchange_code(cfg, code, http)
                access_token = token_payload.get("access_token")
                if not access_token:
                    return RedirectResponse(
                        url="/auth/login?error=no_token", status_code=302
                    )
                user = await fetch_discord_user(access_token, http)
                has_access = await user_has_ui_access(cfg, user.id, http)
            except (httpx.HTTPStatusError, httpx.HTTPError, ValueError):
                return RedirectResponse(
                    url="/auth/login?error=oauth", status_code=302
                )

        if not has_access:
            return HTMLResponse(
                "<h1>Access denied</h1><p>You do not have the required role.</p>",
                status_code=403,
            )

        set_session_user(request.session, user)
        return RedirectResponse(url="/", status_code=302)

    @router.get("/logout")
    def logout(request: Request) -> "RedirectResponse":
        clear_session_user(request.session)
        return RedirectResponse(url="/auth/login", status_code=302)

    return router
