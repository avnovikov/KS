"""Tests for day/night lighting normalization."""

from pathlib import Path

import cv2
import numpy as np

from ks.cartograph.lighting import (
    apply_log_chrom_shift,
    band_match_gray,
    estimate_log_chrom_shift,
    grass_mask,
    load_lighting_reference,
    log_chrominance,
    normalize_band_lighting,
)

REF_PATH = Path("assets/reference/cartograph/lighting-reference.png")


def test_normalize_band_lighting_raises_mean_of_dark_night_grass():
    night = np.full((64, 64, 3), (30, 90, 30), dtype=np.uint8)
    dayish = normalize_band_lighting(night, use_log_chrom=False)
    assert dayish.mean() > night.mean()


def test_normalize_brings_day_and_night_means_closer():
    day = np.full((80, 80, 3), (60, 180, 60), dtype=np.uint8)
    night = np.full((80, 80, 3), (25, 70, 25), dtype=np.uint8)
    ref = day.copy()
    d = normalize_band_lighting(day, reference=ref, use_log_chrom=True).astype(np.float32)
    n = normalize_band_lighting(night, reference=ref, use_log_chrom=True).astype(np.float32)
    raw_gap = abs(float(day.mean()) - float(night.mean()))
    norm_gap = abs(float(d.mean()) - float(n.mean()))
    assert norm_gap < 0.35 * raw_gap


def test_band_match_gray_is_2d_float():
    img = np.zeros((40, 50, 3), dtype=np.uint8)
    img[10:30, 15:35] = (40, 200, 40)
    g = band_match_gray(img)
    assert g.shape == (40, 50)
    assert g.dtype == np.float32


def test_grass_mask_selects_green_pixels():
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    img[:, :] = (40, 200, 40)
    m = grass_mask(img)
    assert int(m.sum()) == 40 * 40


def test_log_chrom_shift_identity_on_same_image():
    img = np.full((32, 32, 3), (50, 180, 55), dtype=np.uint8)
    du, dv = estimate_log_chrom_shift(img, img)
    assert abs(du) < 1e-6
    assert abs(dv) < 1e-6
    out = apply_log_chrom_shift(img, du, dv)
    assert np.allclose(out.astype(np.float32), img.astype(np.float32), atol=2.0)


def test_log_chrom_shift_moves_night_toward_day():
    day = np.full((64, 64, 3), (55, 200, 60), dtype=np.uint8)
    night = np.full((64, 64, 3), (20, 60, 25), dtype=np.uint8)
    du, dv = estimate_log_chrom_shift(night, day)
    shifted = apply_log_chrom_shift(night, du, dv)
    u_n, v_n = log_chrominance(night)
    u_s, v_s = log_chrominance(shifted)
    u_d, v_d = log_chrominance(day)
    mask = grass_mask(day)
    before = abs(float(u_n[mask].mean() - u_d[mask].mean())) + abs(
        float(v_n[mask].mean() - v_d[mask].mean())
    )
    after = abs(float(u_s[mask].mean() - u_d[mask].mean())) + abs(
        float(v_s[mask].mean() - v_d[mask].mean())
    )
    assert after < before


def test_load_lighting_reference_from_assets():
    if not REF_PATH.is_file():
        return
    load_lighting_reference.cache_clear()
    ref = load_lighting_reference(str(REF_PATH))
    assert ref is not None
    assert ref.ndim == 3
    assert ref.shape[2] == 3


def test_normalize_with_file_reference_reduces_log_chrom_spread():
    if not REF_PATH.is_file():
        return
    ref = cv2.imread(str(REF_PATH))
    assert ref is not None
    day = np.full((80, 80, 3), (60, 180, 60), dtype=np.uint8)
    night = np.full((80, 80, 3), (25, 70, 25), dtype=np.uint8)
    load_lighting_reference.cache_clear()

    def chrom_spread(a: np.ndarray, b: np.ndarray) -> float:
        ma, mb = grass_mask(a), grass_mask(b)
        ua, va = log_chrominance(a)
        ub, vb = log_chrominance(b)
        return abs(float(ua[ma].mean() - ub[mb].mean())) + abs(
            float(va[ma].mean() - vb[mb].mean())
        )

    raw = chrom_spread(day, night)
    nd = normalize_band_lighting(day)
    nn = normalize_band_lighting(night)
    norm = chrom_spread(nd, nn)
    assert norm < raw
