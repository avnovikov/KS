from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Match:
    """Top-left corner of a template match in the haystack image."""

    x: int
    y: int
    score: float


def match_template(
    haystack_bgr: np.ndarray,
    needle_bgr: np.ndarray,
    threshold: float,
) -> Match | None:
    if haystack_bgr.ndim != 3 or needle_bgr.ndim != 3:
        raise ValueError("haystack_bgr and needle_bgr must be 3-channel BGR images")
    if haystack_bgr.shape[0] < needle_bgr.shape[0] or haystack_bgr.shape[1] < needle_bgr.shape[1]:
        raise ValueError("needle must not be larger than haystack")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1]; got {threshold}")

    result = cv2.matchTemplate(haystack_bgr, needle_bgr, cv2.TM_CCOEFF_NORMED)
    _, max_score, _, top_left = cv2.minMaxLoc(result)

    # Constant-colour templates have zero variance, so CCOEFF_NORMED is undefined (scores 0).
    if max_score < threshold and float(np.std(needle_bgr)) < 1e-6:
        result = cv2.matchTemplate(haystack_bgr, needle_bgr, cv2.TM_CCORR_NORMED)
        _, max_score, _, top_left = cv2.minMaxLoc(result)

    if max_score < threshold:
        return None

    x, y = top_left
    return Match(x=int(x), y=int(y), score=float(max_score))
