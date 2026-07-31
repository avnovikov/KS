"""Deduplicate StructureHit lists across overlapping samples."""

from __future__ import annotations

import re

from ks.cartograph.models import StructureHit

_SPACE = re.compile(r"\s+")


def _norm_label(label: str) -> str:
    return _SPACE.sub(" ", label.strip().lower())


def _similar(a: str, b: str) -> bool:
    na, nb = _norm_label(a), _norm_label(b)
    if na == nb:
        return True
    if len(na) >= 4 and (na in nb or nb in na):
        return True
    return False


def dedupe_hits(
    hits: list[StructureHit],
    *,
    tile_tol: int = 1,
    merge_banners: bool = False,
) -> list[StructureHit]:
    """Merge hits with similar labels within ``tile_tol`` Chebyshev tiles.

    Alliance banners are never auto-merged unless ``merge_banners=True``.
    """
    if tile_tol < 0:
        raise ValueError(f"tile_tol must be >= 0; got {tile_tol}")

    kept: list[StructureHit] = []
    for hit in hits:
        if hit.kind == "banner" and not merge_banners:
            kept.append(hit)
            continue
        matched = False
        for i, prev in enumerate(kept):
            if prev.kind == "banner" and not merge_banners:
                continue
            if prev.kind != hit.kind:
                continue
            if not _similar(prev.label, hit.label):
                continue
            if max(abs(prev.x - hit.x), abs(prev.y - hit.y)) > tile_tol:
                continue
            # Prefer the one with a longer label / explicit id.
            if (hit.id and not prev.id) or len(hit.label) > len(prev.label):
                kept[i] = hit
            matched = True
            break
        if not matched:
            kept.append(hit)
    return kept
