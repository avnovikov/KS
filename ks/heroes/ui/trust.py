"""Diff pre/post-rescan inventory snapshots into per-row trust flags.

After an OCR rescan the user spot-checks the inventory against the game
rather than trusting it blindly. This module produces the map the UI needs
to point that spot-check at the rows worth looking at: which are brand new,
which changed, and which OCR could not read completely.

Precedence when a row matches more than one condition: **incomplete wins
over new**. A row missing progression data needs the same manual check
whether or not it is brand new, so folding that into a bare "new" flag would
throw away the more actionable signal. "new" and "changed" can never
collide on the same row by construction — a row is only "new" when its key
is absent from `before` — so incomplete-over-new is the only precedence
rule this module needs.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable, TypeVar

from ks.heroes.gear_models import GearRecord
from ks.heroes.models import HeroRecord
from ks.heroes.ui.power import normalize_rarity

_MASTERY_REQUIRED_RARITIES = {"epic", "mythic", "red"}

_Row = TypeVar("_Row")


def _safe_normalize_rarity(rarity: str | None) -> str | None:
    """normalize_rarity() raises on blank/unknown rarity; treat that as
    "no mastery expectation to check" rather than propagating the error."""
    try:
        return normalize_rarity(rarity)
    except ValueError:
        return None


def _gear_incomplete(piece: GearRecord) -> bool:
    if piece.enhancement_level is None:
        return True
    rarity = _safe_normalize_rarity(piece.rarity)
    return rarity in _MASTERY_REQUIRED_RARITIES and piece.mastery_level is None


def _gear_signature(piece: GearRecord) -> tuple[object, ...]:
    """Fields that make a gear row "changed": identity + progression only.

    Excludes scraped_at, raw_text, and detail_screenshot — OCR rewrites
    those on every rescan even when nothing else moved, so comparing them
    would mark every row "changed" every time. Also excludes `stats` (the
    parsed conquest/expedition numbers): those are OCR-derived from the
    same enhancement/mastery/power already compared here, so including
    them would only add noise from OCR misreads without a new signal.
    """
    return (
        piece.name,
        piece.troop_type,
        piece.slot,
        piece.rarity,
        piece.enhancement_level,
        piece.mastery_level,
        piece.power,
        piece.equipped,
        piece.equipped_hero,
    )


def _hero_incomplete(hero: HeroRecord) -> bool:
    return hero.stars is None or hero.power is None


def _hero_signature(hero: HeroRecord) -> tuple[object, ...]:
    """Fields that make a hero row "changed": identity + progression only.

    Excludes scraped_at and name_screenshot for the same reason
    _gear_signature excludes their gear equivalents: rewritten every scan
    regardless of whether stats moved. Also excludes `stats` and `skills`
    (OCR-derived detail parsed from the roster/skill screens) — power,
    level, and stars already capture "did this hero's progression move,"
    so folding in nested skill/stat text would only add OCR-misread noise.
    """
    return (
        hero.power,
        hero.level,
        hero.rarity,
        hero.troop_type,
        hero.escorts,
        hero.stars,
        hero.pellets,
    )


def _diff_rows(
    before: list[_Row],
    after: list[_Row],
    *,
    key_fn: Callable[[_Row], str],
    incomplete_fn: Callable[[_Row], bool],
    signature_fn: Callable[[_Row], tuple[object, ...]],
) -> dict[str, str]:
    """Shared new/changed/incomplete diff, keyed by key_fn(record).

    Rows unchanged in both content and completeness are omitted from the
    result — presence in the map is itself the "look at this row" signal.
    """
    before_by_key = {key_fn(record): record for record in before}
    flags: dict[str, str] = {}
    for record in after:
        key = key_fn(record)
        if incomplete_fn(record):
            flags[key] = "incomplete"
            continue
        prev = before_by_key.get(key)
        if prev is None:
            flags[key] = "new"
        elif signature_fn(prev) != signature_fn(record):
            flags[key] = "changed"
    return flags


def flag_gear_rows(before: list[GearRecord], after: list[GearRecord]) -> dict[str, str]:
    """Diff two gear snapshots into a `piece_id -> flag` trust map.

    A piece is "incomplete" when `enhancement_level is None`, or when
    `rarity` is epic/mythic/red and `mastery_level is None` — those
    rarities always carry a mastery track in this game, so a missing
    mastery there is an OCR miss, not "not started yet" (blue/green gear
    has no mastery track at all, so missing mastery there is expected).

    A piece is "new" when its `piece_id` was not present in `before`, and
    "changed" when it was present but its name, troop_type, slot, rarity,
    enhancement_level, mastery_level, power, or equip state differs (see
    `_gear_signature` for exactly which fields and why).

    See the module docstring for the new-vs-incomplete precedence rule.
    """
    return _diff_rows(
        before,
        after,
        key_fn=lambda p: p.piece_id,
        incomplete_fn=_gear_incomplete,
        signature_fn=_gear_signature,
    )


def flag_hero_rows(before: list[HeroRecord], after: list[HeroRecord]) -> dict[str, str]:
    """Diff two roster snapshots into a `name -> flag` trust map.

    Heroes rescans upsert rather than replace (see `app.api_rescan_heroes`),
    so `after` is the full current roster — untouched heroes plus whatever
    was upserted this scan — while `before` is the pre-rescan snapshot; a
    hero is "new" only the first time its name appears, never again on
    later scans.

    A hero is "incomplete" when `stars is None` or `power is None` — the
    two fields the trust UI most depends on, and the two OCR most often
    misses on a partial pellet-bar or a busy roster tile.

    A hero is "changed" when it was present before and its power, level,
    rarity, troop_type, escorts, stars, or pellets differs (see
    `_hero_signature` for exactly which fields and why).

    See the module docstring for the new-vs-incomplete precedence rule.
    """
    return _diff_rows(
        before,
        after,
        key_fn=lambda h: h.name,
        incomplete_fn=_hero_incomplete,
        signature_fn=_hero_signature,
    )


def summarize_flags(flags: dict[str, str]) -> dict[str, object]:
    """Build the rescan API's `trust` payload from a flags map.

    Tallies the values `flag_gear_rows`/`flag_hero_rows` already produced
    rather than recomputing anything, so `new + changed + incomplete`
    always equals `len(flags)` — the counts can never drift from the map
    they summarize.
    """
    counts = Counter(flags.values())
    return {
        "flags": dict(flags),
        "new": counts.get("new", 0),
        "changed": counts.get("changed", 0),
        "incomplete": counts.get("incomplete", 0),
    }
