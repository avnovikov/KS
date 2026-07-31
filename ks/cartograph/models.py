"""Typed structure hits for cartograph digitization."""

from __future__ import annotations

from dataclasses import dataclass


# Approximate diamond footprints. Exact popup sizes may differ; OCR can refine.
FOOTPRINTS: dict[str, tuple[int, int]] = {
    "city": (2, 2),
    "mill": (2, 2),  # alliance wood/mill-class resources
    "banner": (2, 2),
    "building": (2, 2),  # alliance quarry / iron mine class
    "trap": (3, 3),
    "hq": (5, 5),
    "rss": (1, 1),
    "beast": (1, 1),
    "bread": (1, 1),
    "wood": (1, 1),
    "stone": (1, 1),
    "iron": (1, 1),
    "unknown": (1, 1),
}


def footprint_for(kind: str, label: str = "") -> tuple[int, int]:
    """Return approximate (w, h) tiles for a kind, with light OCR overrides."""
    if kind not in FOOTPRINTS and kind != "unknown":
        raise ValueError(f"unknown kind {kind!r}; known={sorted(FOOTPRINTS)}")
    base = FOOTPRINTS.get(kind, (1, 1))
    text = (label or "").lower()
    # Larger named structures seen on the world map.
    if "plains hq" in text or "alliance hq" in text:
        return (5, 5)
    if "hunting trap" in text or "bear trap" in text:
        return (3, 3)
    if "fortress" in text or "stronghold" in text:
        return (4, 4)
    return base


@dataclass(frozen=True)
class StructureHit:
    label: str
    kind: str
    x: int
    y: int
    w: int
    h: int
    source: str = ""
    id: str | None = None

    @staticmethod
    def from_kind(
        label: str,
        kind: str,
        x: int,
        y: int,
        *,
        source: str = "",
        id: str | None = None,
    ) -> StructureHit:
        if kind not in FOOTPRINTS:
            raise ValueError(f"unknown kind {kind!r}; known={sorted(FOOTPRINTS)}")
        w, h = footprint_for(kind, label)
        return StructureHit(
            label=label, kind=kind, x=x, y=y, w=w, h=h, source=source, id=id
        )
