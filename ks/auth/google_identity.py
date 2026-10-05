"""Reduce a Google profile to a verified email safe to store on disk."""

from __future__ import annotations

import re
from typing import Any


_EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


class UnverifiedGoogleEmail(ValueError):
    """Google returned an address that is not a verified email."""


def email_path_segment(email: str) -> str:
    """Return a lowercased email that is one directory name.

    The segment is the only Google identity we persist. Slashes, backslashes,
    and ``..`` are rejected so the value cannot escape ``users_root/google``.
    """

    if not isinstance(email, str):
        raise ValueError(f"email must be a string; got {type(email).__name__}")
    normalized = email.strip().lower()
    if not normalized or any(char in normalized for char in "/\\\x00"):
        raise ValueError(f"email is not a safe path segment: {email!r}")
    if ".." in normalized:
        raise ValueError(f"email is not a safe path segment: {email!r}")
    if _EMAIL_RE.fullmatch(normalized) is None:
        raise ValueError(f"email is not a valid address: {email!r}")
    return normalized


def verified_email_from_profile(payload: Any) -> str:
    """Read only a verified email from a Google userinfo payload.

    Name, photo, and the Google account id are ignored on purpose.
    """

    if not isinstance(payload, dict):
        raise ValueError("Google user response must be a JSON object")
    if payload.get("email_verified") is not True:
        raise UnverifiedGoogleEmail("Google email is not verified")
    return email_path_segment(payload.get("email"))
