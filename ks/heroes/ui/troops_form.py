"""Shape a raw troops document into the rows the troops editor renders.

The editor page is server-rendered from TroopStore.load_raw(), so this has
to cope with everything that can legitimately (or accidentally) be sitting
in that file:

* int tier keys (the YAML seed) *and* string tier keys (every PUT
  round-trips through JSON, whose object keys are always strings);
* a flat int type block — `infantry: 5000` — which the optimisers' loader
  reads as 5000 tier-1 troops (see _parse_type_block);
* tiers outside 1..11, which must still be rendered: a save replaces a whole
  type block, so a tier the form never showed would be silently deleted;
* junk from a hand edit, which must render as zeros rather than raise — the
  page route separately surfaces *why* the document is unhappy via the same
  validator /api/troops uses.

Deliberately does no validation: rendering is best-effort display, and
validation belongs to troops_config_from_dict on the way back in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TYPE_KEYS: tuple[str, ...] = ("infantry", "cavalry", "archers")
TYPE_LABELS: dict[str, str] = {
    "infantry": "Infantry",
    "cavalry": "Cavalry",
    "archers": "Archers",
}
#: Tiers the form always renders, even when absent from the document.
BASE_TIERS: tuple[int, ...] = tuple(range(1, 12))


@dataclass(frozen=True)
class TierRow:
    """One `tier: count` input in a type card."""

    tier: int
    count: int


@dataclass(frozen=True)
class TroopTypeForm:
    """One stacked per-type card (infantry/cavalry/archers)."""

    key: str
    label: str
    tiers: tuple[TierRow, ...]

    @property
    def total(self) -> int:
        """Read-only sum shown in the card header."""
        return sum(row.count for row in self.tiers)


@dataclass(frozen=True)
class TroopsForm:
    """Everything the troops editor template needs."""

    march_capacity: int
    truegold: int
    types: tuple[TroopTypeForm, ...]


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a YAML scalar to int, falling back to `default`.

    Booleans are rejected on purpose: `True` would otherwise render as 1 and
    silently become a real troop count on the next save.
    """
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tier_counts(raw: Any) -> dict[int, int]:
    """Read one type block as {tier: count}, dropping what cannot be a tier."""
    if isinstance(raw, bool):
        return {}
    if isinstance(raw, int):
        # Flat int block: the loader treats it as that many tier-1 troops.
        return {1: raw} if raw else {}
    if not isinstance(raw, dict):
        return {}
    counts: dict[int, int] = {}
    for key, value in raw.items():
        if isinstance(key, bool):
            continue
        try:
            tier = int(key)
        except (TypeError, ValueError):
            continue
        if tier < 1:
            continue
        counts[tier] = _as_int(value)
    return counts


def troops_form_model(raw: dict[str, Any]) -> TroopsForm:
    """Build the editor's view of `raw` (never raises on bad content)."""
    if not isinstance(raw, dict):
        raw = {}
    types: list[TroopTypeForm] = []
    for key in TYPE_KEYS:
        counts = _tier_counts(raw.get(key))
        tiers = sorted(set(BASE_TIERS) | set(counts))
        types.append(
            TroopTypeForm(
                key=key,
                label=TYPE_LABELS[key],
                tiers=tuple(TierRow(tier, counts.get(tier, 0)) for tier in tiers),
            )
        )
    return TroopsForm(
        march_capacity=_as_int(raw.get("march_capacity")),
        truegold=_as_int(raw.get("truegold")),
        types=tuple(types),
    )
