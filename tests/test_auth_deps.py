"""Tests for auth dependencies."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def test_require_user_returns_401_when_session_empty():
    from ks.auth import require_user

    app = FastAPI()

    @app.middleware("http")
    async def add_empty_session(request, call_next):
        request.scope["session"] = {}
        return await call_next(request)

    @app.get("/protected")
    def protected(user=Depends(require_user)):
        return {"user": user.username}

    client = TestClient(app)
    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}

