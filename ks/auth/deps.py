"""FastAPI dependencies for auth."""

from __future__ import annotations

from fastapi import HTTPException, Request

from ks.auth.session_user import SessionUser, get_session_user


def require_user(request: Request) -> SessionUser:
    user = get_session_user(request.session)
    if user is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user

