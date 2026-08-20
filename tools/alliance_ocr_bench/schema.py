"""Gold set and OCR hit schemas for the alliance OCR bake-off."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GoldRow:
    id: str
    shot: str
    roi: tuple[int, int, int, int] | None
    name: str
    power: float
    tag: str = ""
    rank_hint: str = ""


@dataclass(frozen=True)
class OcrHit:
    text: str
    conf: float
    box_xyxy: tuple[float, float, float, float]


def _parse_roi(raw: Any) -> tuple[int, int, int, int] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise ValueError(f"roi must be null or 4 ints; got {raw!r}")
    return (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))


def _parse_gold_row(raw: Any, index: int) -> GoldRow:
    if not isinstance(raw, dict):
        raise ValueError(f"gold[{index}] must be an object")
    for key in ("id", "shot", "name", "power"):
        if key not in raw:
            raise ValueError(f"gold[{index}] missing required field {key!r}")
    power = float(raw["power"])
    if power <= 0:
        raise ValueError(f"gold[{index}] power must be > 0; got {power}")
    name = str(raw["name"]).strip()
    if not name:
        raise ValueError(f"gold[{index}] name must be non-empty")
    return GoldRow(
        id=str(raw["id"]),
        shot=str(raw["shot"]),
        roi=_parse_roi(raw.get("roi")),
        name=name,
        power=power,
        tag=str(raw.get("tag", "")),
        rank_hint=str(raw.get("rank_hint", "")),
    )


def load_gold(path: Path) -> list[GoldRow]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("gold file must be a JSON list")
    return [_parse_gold_row(item, i) for i, item in enumerate(data)]
