"""Named preprocess profiles for the OCR bake-off grid."""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

ProfileFn = Callable[[np.ndarray], np.ndarray]


def _as_bgr(gray: np.ndarray) -> np.ndarray:
    if gray.ndim == 2:
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return gray


def _scale(image: np.ndarray, factor: float) -> np.ndarray:
    if factor == 1.0:
        return image
    return cv2.resize(
        image,
        None,
        fx=factor,
        fy=factor,
        interpolation=cv2.INTER_CUBIC,
    )


def _to_gray(bgr: np.ndarray) -> np.ndarray:
    if bgr.ndim == 2:
        return bgr
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _profile_raw(bgr: np.ndarray) -> np.ndarray:
    return bgr.copy()


def _profile_gray(bgr: np.ndarray) -> np.ndarray:
    return _as_bgr(_to_gray(bgr))


def _profile_gray_x2(bgr: np.ndarray) -> np.ndarray:
    return _as_bgr(_scale(_to_gray(bgr), 2.0))


def _profile_gray_x3(bgr: np.ndarray) -> np.ndarray:
    return _as_bgr(_scale(_to_gray(bgr), 3.0))


def _profile_clahe_x2(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return _as_bgr(_scale(clahe.apply(gray), 2.0))


def _profile_otsu_x2(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    _thresh, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _as_bgr(_scale(binary, 2.0))


def _profile_otsu_x2_inv(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    _thresh, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    return _as_bgr(_scale(binary, 2.0))


PROFILES: dict[str, ProfileFn] = {
    "raw": _profile_raw,
    "gray": _profile_gray,
    "gray_x2": _profile_gray_x2,
    "gray_x3": _profile_gray_x3,
    "clahe_x2": _profile_clahe_x2,
    "otsu_x2": _profile_otsu_x2,
    "otsu_x2_inv": _profile_otsu_x2_inv,
}


def list_profiles() -> list[str]:
    return sorted(PROFILES)


def apply_profile(name: str, bgr: np.ndarray) -> np.ndarray:
    if name not in PROFILES:
        raise ValueError(f"unknown preprocess profile {name!r}")
    if bgr.ndim not in (2, 3):
        raise ValueError(f"image must be 2D or 3D; got shape {bgr.shape}")
    return PROFILES[name](bgr)
