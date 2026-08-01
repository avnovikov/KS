"""Tests for cartograph mask + crop."""

import numpy as np

from ks.cartograph.mask import (
    MaskConfig,
    apply_mask,
    bluestacks_mask_config,
    crop_map_band,
    mask_and_crop,
)


def test_apply_mask_paints_fractional_rect() -> None:
    img = np.full((100, 200, 3), 128, dtype=np.uint8)
    cfg = MaskConfig(rects=((0.0, 0.0, 1.0, 0.2),))
    out = apply_mask(img, cfg)
    assert (out[0:20, :, :] == 0).all()
    assert (out[20:, :, :] == 128).all()


def test_crop_map_band() -> None:
    img = np.zeros((100, 50, 3), dtype=np.uint8)
    img[20:80, :, :] = 255
    cfg = MaskConfig(rects=(), crop_top=0.2, crop_bottom=0.8)
    band = crop_map_band(img, cfg)
    assert band.shape == (60, 50, 3)
    assert (band == 255).all()


def test_mask_and_crop_combined() -> None:
    img = np.full((100, 100, 3), 200, dtype=np.uint8)
    cfg = MaskConfig(
        rects=((0.0, 0.0, 1.0, 0.1),),
        crop_top=0.1,
        crop_bottom=0.9,
    )
    band = mask_and_crop(img, cfg)
    assert band.shape[0] == 80
    assert (band[0, 0] == 200).all()


def test_bluestacks_mask_crops_map_band() -> None:
    cfg = bluestacks_mask_config()
    img = np.full((1920, 1080, 3), 100, dtype=np.uint8)
    band = mask_and_crop(img, cfg)
    h, w = img.shape[:2]
    y0 = int(round(h * cfg.crop_top))
    y1 = int(round(h * cfg.crop_bottom))
    x0 = int(round(w * cfg.crop_left))
    x1 = int(round(w * cfg.crop_right))
    assert band.shape == (y1 - y0, x1 - x0, 3)
    assert band.shape[1] < 1080
    # PC Marching / Events chrome must be outside the kept band.
    assert cfg.crop_left >= 0.28
    assert cfg.crop_right <= 0.80


def test_bluestacks_mask_excludes_marching_column() -> None:
    """Marching 3/4 column (left ~0.34×W) is cropped out of the map band."""
    cfg = bluestacks_mask_config()
    img = np.full((1920, 1080, 3), 180, dtype=np.uint8)
    img[420:460, 80:120] = (200, 180, 40)
    band = mask_and_crop(img, cfg)
    h, w = img.shape[:2]
    x0 = int(round(w * cfg.crop_left))
    assert x0 > 120
    assert cfg.crop_left >= 0.34
    assert band.shape[1] < w * 0.5

