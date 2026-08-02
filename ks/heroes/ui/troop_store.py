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

# Used only when ensure_exists() has no seed_from configured at all — every
# real caller (app.py) always supplies seed_from=<repo>/config/troops.yaml, so
# this is just a safe, structurally valid fallback rather than a crash. A
# *configured* seed_from that points at a missing file is a different,
# louder failure — see ensure_exists() below (Minor 10).
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

        If `seed_from` is configured but does not exist on disk (e.g. the
        REPO_ROOT guess in app.py is wrong, such as when installed as a
        package), this fails loudly with FileNotFoundError naming the path
        it looked for — rather than silently seeding an all-zero army via
        _EMPTY_TROOPS, which would be reachable but wrong (Minor 10). The
        no-seed-configured case (seed_from=None) is unaffected: it still
        falls back to _EMPTY_TROOPS as before.
        """
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._seed_from is None:
            self._write(_EMPTY_TROOPS)
            return
        if not self._seed_from.is_file():
            raise FileNotFoundError(
                f"troops seed file not found: {self._seed_from}"
            )
        shutil.copy2(self._seed_from, self.path)

    def load_raw(self) -> dict[str, Any]:
        """Return the troops file contents as a plain dict (no validation).

        Calls ensure_exists() first, so a read can create the file (seeded
        or empty) as a side effect if it does not exist yet. The app seeds
        at startup anyway, so this is normally a no-op, but callers should
        not be surprised that a GET can write to disk.

        Raises yaml.YAMLError if the on-disk file is not parseable YAML, or
        ValueError if it parses to something other than a mapping.
        """
        self.ensure_exists()
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(
                f"{self.path} must contain a mapping; got {type(raw).__name__}"
            )
        return raw

    def save_raw(self, data: dict[str, Any]) -> dict[str, Any]:
        """Merge `data` into the existing document, validate, and persist it.

        Top-level merge semantics (documented here because Task 3's editor
        page is built against this contract): keys present in `data` replace
        their counterparts in the on-disk document; keys `data` omits are
        preserved from what is already there (so a PUT that omits e.g.
        truegold does not delete it). A type block (infantry/cavalry/
        archers) that IS present in `data` replaces that whole block rather
        than being deep-merged tier by tier — a client that wants to clear a
        tier to 0 can just send the full replacement block without it.

        Trade-off (deliberate): persisting the merged dict verbatim — rather
        than a value reconstructed from TroopsConfig — is what lets fields
        validation ignores (e.g. truegold) round-trip faithfully, but it
        also means arbitrary junk keys the caller sends persist into the
        YAML right alongside the fields we understand.

        An existing on-disk document that fails to *parse* (corrupt YAML —
        e.g. from the non-atomic write_text below being interrupted mid-
        save) is treated as "nothing to merge from", not as a merge
        failure: merging into garbage is meaningless anyway, and a complete,
        valid `data` must still be able to repair a corrupted file through
        this same method — that self-healing path existed when save_raw was
        a blind overwrite, and merging must not remove it. A document that
        parses but is not a mapping (e.g. a YAML list) is a different,
        narrower failure and is NOT given this treatment: load_raw()'s
        ValueError for that case still propagates (a body that omits every
        key would otherwise "merge" into an empty document, which is likely
        not what a caller sending that shape intended).

        Validates the *merged* result via troops_config_from_dict. Raises
        ValueError on an invalid merged shape: either troops_config_from_dict's
        own ValueError messages, or its TypeError (e.g. `int(None)` for a
        null march_capacity/tier count) re-raised as ValueError so HTTP
        callers can map it to 422 the same way as any other validation
        failure. load_raw()'s ValueError (non-mapping content) also
        propagates as-is. FileNotFoundError can propagate from
        ensure_exists() if `seed_from` is configured but missing (Minor 10)
        — a deploy/config error, not a data error, so it is not swallowed
        here.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"troops data must be a mapping; got {type(data).__name__}"
            )
        try:
            existing = self.load_raw()
        except yaml.YAMLError:
            existing = {}
        merged = {**existing, **data}
        try:
            troops_config_from_dict(merged)
        except TypeError as exc:
            raise ValueError(f"invalid troops data: {exc}") from exc
        self._write(merged)
        return merged

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )
