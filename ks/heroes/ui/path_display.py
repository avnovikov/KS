"""Redact Discord snowflake user ids in paths shown in the UI."""

from __future__ import annotations

import re

# Discord snowflakes are typically 17–19 digits; require 15+ to avoid
# masking short numeric path segments (ports, years, etc.).
_SNOWFLAKE_RE = re.compile(r"(?<![0-9])([0-9]{15,20})(?![0-9])")

_PATH_CONTEXT_KEYS = frozenset(
    {
        "gear_dir",
        "heroes_dir",
        "governor_dir",
        "research_dir",
        "troops_path",
    }
)


def mask_discord_id_in_path(text: str) -> str:
    """Replace long numeric ids with ``prefix***suffix`` (e.g. ``146***2142``)."""

    if not text:
        return text

    def _repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        if len(raw) < 10:
            return raw
        return f"{raw[:3]}***{raw[-4:]}"

    return _SNOWFLAKE_RE.sub(_repl, text)


def mask_path_fields(context: dict[str, object]) -> dict[str, object]:
    """Return a shallow copy with known path fields redacted for display."""

    out = dict(context)
    for key in _PATH_CONTEXT_KEYS:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = mask_discord_id_in_path(value)
    return out
