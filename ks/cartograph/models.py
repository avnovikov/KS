"""Typed structure hits for cartograph digitization."""

from __future__ import annotations

from dataclasses import dataclass


FOOTPRINTS: dict[str, tuple[int, int]] = {
    "city": (2, 2),
    "mill": (1, 1),
    "banner": (1, 1),
    "building": (1, 1),
    "trap": (3, 3),
    "hq": (5, 5),
    "rss": (1, 1),
    "beast": (1, 1),
    "bread": (1, 1),
    "wood": (1, 1),
    "stone": (1, 1),
    "iron": (1, 1),
}


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
        w, h = FOOTPRINTS[kind]
        return StructureHit(
            label=label, kind=kind, x=x, y=y, w=w, h=h, source=source, id=id
        )
