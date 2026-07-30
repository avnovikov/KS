"""Day/night lighting normalization for mosaic match + paste.

KingShot map grass shifts hue/value between day and night. Pixel NCC on raw
BGR then locks onto the wrong overlap. Log-chrominance shift toward a reference
mid-day band, then HSV anchor, so backgrounds look the same; match on edges.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

# Target mid-day grass brightness / sat after normalize.
_TARGET_V = 145.0
_TARGET_S = 85.0

_DEFAULT_REFERENCE = Path("assets/reference/cartograph/lighting-reference.png")
_MIN_GRASS_PIXELS = 500


def grass_mask(band: np.ndarray) -> np.ndarray:
    """Pixels likely to be grass / foliage (HSV heuristics)."""
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    grass = (h >= 30) & (h <= 95) & (s > 25) & (v > 20)
    if int(grass.sum()) >= _MIN_GRASS_PIXELS:
        return grass
    return v > 12


def log_chrominance(band: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (u, v) where u=log(G/R), v=log(G/B) per pixel."""
    f = band.astype(np.float32) + 1.0
    g, r, b = f[:, :, 1], f[:, :, 2], f[:, :, 0]
    return np.log(g / r), np.log(g / b)


def estimate_log_chrom_shift(
    src: np.ndarray,
    ref: np.ndarray,
    *,
    mask: np.ndarray | None = None,
) -> tuple[float, float]:
    """Median log-chrom translation from src toward ref on masked pixels."""
    if ref.shape[:2] != src.shape[:2]:
        ref = cv2.resize(ref, (src.shape[1], src.shape[0]))
    if mask is None:
        mask = grass_mask(src) & grass_mask(ref)
    if int(mask.sum()) < 50:
        mask = grass_mask(src)
    u_src, v_src = log_chrominance(src)
    u_ref, v_ref = log_chrominance(ref)
    du = float(np.median(u_ref[mask] - u_src[mask]))
    dv = float(np.median(v_ref[mask] - v_src[mask]))
    return du, dv


def apply_log_chrom_shift(
    band: np.ndarray,
    du: float,
    dv: float,
) -> np.ndarray:
    """Apply log-chrom translation and reconstruct BGR."""
    u, v = log_chrominance(band)
    u2 = u + du
    v2 = v + dv
    f = band.astype(np.float32) + 1.0
    g = f[:, :, 1]
    g2 = g * np.exp(du)
    r2 = g2 / np.exp(u2)
    b2 = g2 / np.exp(v2)
    out = np.stack([b2 - 1.0, g2 - 1.0, r2 - 1.0], axis=2)
    return np.clip(out, 0, 255).astype(np.uint8)


@lru_cache(maxsize=1)
def load_lighting_reference(path: str | None = None) -> np.ndarray | None:
    """Load cached BGR reference band; None if missing."""
    p = Path(path) if path else _DEFAULT_REFERENCE
    if not p.is_file():
        return None
    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    return img


def _hsv_anchor(
    band: np.ndarray,
    *,
    target_v: float = _TARGET_V,
    target_s: float = _TARGET_S,
) -> np.ndarray:
    """Scale HSV V/S toward targets; nudge grass hue toward mid-day green."""
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV).astype(np.float32)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    live = v > 12.0
    if not bool(live.any()):
        return band.copy()
    v_mean = float(v[live].mean()) + 1e-3
    s_mean = float(s[live].mean()) + 1e-3
    v2 = v.copy()
    s2 = s.copy()
    h2 = h.copy()
    v2[live] = np.clip(v[live] * (target_v / v_mean), 0, 255)
    s2[live] = np.clip(s[live] * (target_s / s_mean), 0, 255)
    grass = live & (h >= 30.0) & (h <= 95.0) & (s > 25.0)
    if bool(grass.any()):
        h2[grass] = 0.55 * h[grass] + 0.45 * 55.0
    out = np.stack([h2, s2, v2], axis=2).astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_HSV2BGR)


def normalize_band_lighting(
    band: np.ndarray,
    *,
    reference: np.ndarray | None = None,
    reference_path: str | None = None,
    target_v: float = _TARGET_V,
    target_s: float = _TARGET_S,
    use_log_chrom: bool = True,
) -> np.ndarray:
    """Return a BGR copy with day/night tint stripped to a common mid-day look.

    When a reference band is available, estimate log-chrominance shift on grass
    pixels first (Barron ICCV 2015), then apply HSV brightness/saturation anchor.
    """
    if band.ndim != 3 or band.shape[2] != 3:
        raise ValueError(f"band must be HxWx3; got {band.shape}")

    work = band
    ref = reference
    if ref is None and use_log_chrom:
        ref = load_lighting_reference(reference_path)
    if ref is not None and use_log_chrom:
        du, dv = estimate_log_chrom_shift(band, ref)
        work = apply_log_chrom_shift(band, du, dv)

    return _hsv_anchor(work, target_v=target_v, target_s=target_s)


def normalize_background_lighting(
    band: np.ndarray,
    *,
    reference: np.ndarray | None = None,
    reference_path: str | None = None,
    target_v: float = _TARGET_V,
    target_s: float = _TARGET_S,
    use_log_chrom: bool = True,
) -> np.ndarray:
    """Normalize terrain while retaining original structure and unit colors."""
    normalized = normalize_band_lighting(
        band,
        reference=reference,
        reference_path=reference_path,
        target_v=target_v,
        target_s=target_s,
        use_log_chrom=use_log_chrom,
    )
    background = grass_mask(band)
    output = band.copy()
    output[background] = normalized[background]
    return output


def band_match_gray(band: np.ndarray) -> np.ndarray:
    """Lighting-robust float grayscale for NCC: structure edges, not grass tone."""
    norm = normalize_band_lighting(band)
    g = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    edges = cv2.Laplacian(g, cv2.CV_32F, ksize=3)
    return np.abs(edges)
