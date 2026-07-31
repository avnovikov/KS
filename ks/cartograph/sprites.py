"""Multi-scale sprite template matching for beasts and resources.

Templates are the first detector; export hooks prepare a YOLO graduation path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import cv2
import numpy as np

from ks.cartograph.entities import EntityObservation
from ks.cartograph.models import FOOTPRINTS

DEFAULT_SCALES = (0.75, 1.0, 1.25, 1.5)
DEFAULT_MATCH_THRESHOLD = 0.72
DEFAULT_NMS_RADIUS_PX = 28.0

# Map template folder names → catalog kinds.
KIND_BY_TEMPLATE_DIR = {
    "beast": "beast",
    "rss": "rss",
    "wood": "wood",
    "bread": "bread",
    "stone": "stone",
    "iron": "iron",
}


@dataclass(frozen=True)
class SpriteHit:
    kind: str
    pixel_x: float
    pixel_y: float
    confidence: float
    template_id: str


def default_template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "templates" / "cartograph"


def load_templates(root: Path | None = None) -> list[tuple[str, str, np.ndarray]]:
    """Load ``(kind, template_id, bgr_image)`` from class subfolders."""
    base = root or default_template_root()
    if not base.is_dir():
        return []
    loaded: list[tuple[str, str, np.ndarray]] = []
    for folder, kind in sorted(KIND_BY_TEMPLATE_DIR.items()):
        directory = base / folder
        if not directory.is_dir():
            continue
        if kind not in FOOTPRINTS:
            continue
        for path in sorted(directory.glob("*.png")):
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                continue
            loaded.append((kind, path.stem, image))
    return loaded


def match_sprites(
    band: np.ndarray,
    *,
    templates: Sequence[tuple[str, str, np.ndarray]] | None = None,
    scales: Sequence[float] = DEFAULT_SCALES,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    nms_radius_px: float = DEFAULT_NMS_RADIUS_PX,
) -> list[SpriteHit]:
    """Return non-overlapping sprite hits for one masked band."""
    if band.ndim != 3 or band.shape[2] != 3:
        raise ValueError(f"band must be HxWx3; got {band.shape}")
    if not (0.0 < threshold <= 1.0):
        raise ValueError(f"threshold must be in (0, 1]; got {threshold}")
    pack = list(templates) if templates is not None else load_templates()
    if not pack:
        return []

    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    raw: list[SpriteHit] = []
    for kind, template_id, template_bgr in pack:
        template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
        th, tw = template_gray.shape[:2]
        if th < 8 or tw < 8:
            continue
        for scale in scales:
            if scale <= 0:
                continue
            width = max(8, int(round(tw * scale)))
            height = max(8, int(round(th * scale)))
            if height >= gray.shape[0] or width >= gray.shape[1]:
                continue
            scaled = cv2.resize(template_gray, (width, height), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(gray, scaled, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)
            for y, x in zip(*locations):
                score = float(result[y, x])
                raw.append(
                    SpriteHit(
                        kind=kind,
                        pixel_x=x + width / 2.0,
                        pixel_y=y + height / 2.0,
                        confidence=min(1.0, max(1e-3, score)),
                        template_id=template_id,
                    )
                )
    return _nms(raw, radius_px=nms_radius_px)


def sprite_hits_to_observations(
    hits: Sequence[SpriteHit],
    *,
    frame: str,
) -> list[EntityObservation]:
    observations: list[EntityObservation] = []
    for hit in hits:
        observations.append(
            EntityObservation(
                frame=frame,
                pixel_x=hit.pixel_x,
                pixel_y=hit.pixel_y,
                identity=None,
                label=hit.kind,
                kind=hit.kind,
                level=None,
                confidence=hit.confidence,
                provenance="visual_projected",
            )
        )
    return observations


def match_sprite_observations(
    band: np.ndarray,
    *,
    frame: str,
    templates: Sequence[tuple[str, str, np.ndarray]] | None = None,
) -> list[EntityObservation]:
    """Convenience: template match → entity observations."""
    return sprite_hits_to_observations(
        match_sprites(band, templates=templates),
        frame=frame,
    )


def export_yolo_labels_stub(
    *,
    class_names: Sequence[str] = ("beast", "rss", "wood", "bread", "stone", "iron"),
) -> str:
    """Return dataset notes for graduating templates to a YOLO detector."""
    names = ", ".join(class_names)
    return (
        "# YOLO graduation (stub)\n"
        "# 1. Export sprite hits + manual corrections as YOLO txt labels\n"
        f"# 2. classes: {names}\n"
        "# 3. Train yolov8n on assets/templates/cartograph + hard negatives\n"
        "# 4. Replace match_sprites() with detector inference behind the same API\n"
    )


def _nms(hits: Sequence[SpriteHit], *, radius_px: float) -> list[SpriteHit]:
    ordered = sorted(hits, key=lambda item: item.confidence, reverse=True)
    kept: list[SpriteHit] = []
    for hit in ordered:
        if any(
            (hit.pixel_x - other.pixel_x) ** 2 + (hit.pixel_y - other.pixel_y) ** 2
            <= radius_px**2
            for other in kept
        ):
            continue
        kept.append(hit)
    return kept


SpriteMatcher = Callable[..., list[EntityObservation]]
