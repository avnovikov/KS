"""Fractional UI mask + crop for cartograph frames."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MaskConfig:
    """Rects are fractions of native W×H: (x0, y0, x1, y1)."""

    rects: tuple[tuple[float, float, float, float], ...]
    crop_top: float = 0.0
    crop_bottom: float = 1.0
    crop_left: float = 0.0
    crop_right: float = 1.0
    fill: tuple[int, int, int] = (0, 0, 0)


def _frac_to_px(
    h: int, w: int, box: tuple[float, float, float, float]
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    assert 0.0 <= x0 < x1 <= 1.0, box
    assert 0.0 <= y0 < y1 <= 1.0, box
    return (
        int(round(w * x0)),
        int(round(h * y0)),
        int(round(w * x1)),
        int(round(h * y1)),
    )


def apply_mask(image: np.ndarray, cfg: MaskConfig) -> np.ndarray:
    """Return a copy with UI rects painted ``cfg.fill``."""
    assert image.ndim == 3 and image.shape[2] == 3, image.shape
    out = image.copy()
    h, w = out.shape[:2]
    color = np.array(cfg.fill, dtype=out.dtype)
    for box in cfg.rects:
        x0, y0, x1, y1 = _frac_to_px(h, w, box)
        out[y0:y1, x0:x1] = color
    return out


def crop_map_band(image: np.ndarray, cfg: MaskConfig) -> np.ndarray:
    """Crop to the map band after masking (or on a masked copy)."""
    assert image.ndim == 3 and image.shape[2] == 3, image.shape
    h, w = image.shape[:2]
    y0 = int(round(h * cfg.crop_top))
    y1 = int(round(h * cfg.crop_bottom))
    x0 = int(round(w * cfg.crop_left))
    x1 = int(round(w * cfg.crop_right))
    assert 0 <= y0 < y1 <= h, (y0, y1, h)
    assert 0 <= x0 < x1 <= w, (x0, x1, w)
    return image[y0:y1, x0:x1].copy()


def mask_and_crop(image: np.ndarray, cfg: MaskConfig) -> np.ndarray:
    return crop_map_band(apply_mask(image, cfg), cfg)


def bluestacks_mask_config() -> MaskConfig:
    """UI mask for BlueStacks 1080×1920 KingShot portrait.

    Never-touch = HUD / side chrome / search / chat / Marching panel, removed
    by **crop**. PC BlueStacks layouts put Marching 3/4 + return arrows further
    into the map than phone-safe crops (~0.14); ``crop_left`` must clear that
    column (~0.34×W) so buttons never enter the mosaic band.
    """
    return MaskConfig(
        rects=(),
        crop_top=0.14,
        crop_bottom=0.68,
        crop_left=0.34,
        crop_right=0.78,
        fill=(0, 0, 0),
    )
