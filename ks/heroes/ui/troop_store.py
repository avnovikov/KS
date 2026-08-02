"""Persist a UI-editable copy of troops.yaml that every optimiser reads.

The repo ships a seed at config/troops.yaml, but the UI needs a per-install,
user-editable copy (Task 3 builds the editor page on top of this). This
store owns that copy: seeding it on first use, handing back the raw dict for
display, and validating edits the same way the optimisers' loader does
before persisting them.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from ks.heroes.optimize.troops import troops_config_from_dict

# Used only if ensure_exists() has no seed_from and no file exists yet — every
# real caller (app.py) always supplies seed_from=<repo>/config/troops.yaml, so
# this is just a safe, structurally valid fallback rather than a crash.
_EMPTY_TROOPS: dict[str, Any] = {
    "march_capacity": 0,
    "truegold": 0,
    "infantry": 0,
    "cavalry": 0,
    "archers": 0,
}


class TroopStore:
    """Read/write the troops.yaml-shaped file at `path`."""

    def __init__(self, path: Path, *, seed_from: Path | None = None) -> None:
        if not isinstance(path, Path):
            raise TypeError(f"path must be Path; got {type(path).__name__}")
        self.path = path
        self._seed_from = seed_from

    def ensure_exists(self) -> None:
        """Create `path` (seeded from `seed_from`) if it does not exist yet.

        A no-op once the file exists, so it never clobbers UI edits.
        """
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._seed_from is not None and self._seed_from.is_file():
            shutil.copy2(self._seed_from, self.path)
        else:
            self._write(_EMPTY_TROOPS)

    def load_raw(self) -> dict[str, Any]:
        """Return the troops file contents as a plain dict (no validation)."""
        self.ensure_exists()
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(
                f"{self.path} must contain a mapping; got {type(raw).__name__}"
            )
        return raw

    def save_raw(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate `data` via troops_config_from_dict, then persist it.

        Raises ValueError (same messages as troops_config_from_dict) on an
        invalid shape. Persists `data` itself — not a value reconstructed
        from TroopsConfig — so fields validation ignores (e.g. truegold)
        still round-trip faithfully.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"troops data must be a mapping; got {type(data).__name__}"
            )
        troops_config_from_dict(data)
        self._write(data)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )
