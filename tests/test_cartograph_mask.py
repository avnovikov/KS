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
    assert band.shape[0] == int(round(1920 * (cfg.crop_bottom - cfg.crop_top)))
    assert band.shape[1] == int(round(1080 * (cfg.crop_right - cfg.crop_left)))
    assert band.shape[1] < 1080
