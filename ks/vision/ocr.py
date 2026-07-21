import re

import numpy as np
import pytesseract

_RSS_SUFFIX_PATTERN = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KkMm])\s*$",
)
_RSS_PLAIN_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*$")

_MARCH_HMS_PATTERN = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})\s*$",
)
_MARCH_MS_PATTERN = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_MARCH_HM_PATTERN = re.compile(
    r"^\s*(\d+)\s*[hH]\s*(\d+)\s*[mM]\s*$",
)
_MARCH_SECONDS_PATTERN = re.compile(r"^\s*(\d+)\s*[sS]\s*$")


def parse_rss_amount(text: str) -> float:
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")

    suffix_match = _RSS_SUFFIX_PATTERN.match(text)
    if suffix_match:
        value = float(suffix_match.group(1))
        suffix = suffix_match.group(2).upper()
        multiplier = 1_000 if suffix == "K" else 1_000_000
        return value * multiplier

    plain_match = _RSS_PLAIN_PATTERN.match(text)
    if plain_match:
        return float(plain_match.group(1))

    raise ValueError(f"cannot parse RSS amount from {text!r}")


def parse_march_time(text: str) -> float:
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")

    hms_match = _MARCH_HMS_PATTERN.match(text)
    if hms_match:
        hours, minutes, seconds = (int(part) for part in hms_match.groups())
        return float(hours * 3600 + minutes * 60 + seconds)

    ms_match = _MARCH_MS_PATTERN.match(text)
    if ms_match:
        minutes, seconds = (int(part) for part in ms_match.groups())
        return float(minutes * 60 + seconds)

    hm_match = _MARCH_HM_PATTERN.match(text)
    if hm_match:
        hours, minutes = (int(part) for part in hm_match.groups())
        return float(hours * 3600 + minutes * 60)

    seconds_match = _MARCH_SECONDS_PATTERN.match(text)
    if seconds_match:
        return float(int(seconds_match.group(1)))

    raise ValueError(f"cannot parse march time from {text!r}")


def ocr_region(image: np.ndarray, box: tuple[int, int, int, int]) -> str:
    """Run OCR on a cropped region. box is (x, y, width, height)."""
    if image.ndim not in (2, 3):
        raise ValueError("image must be a 2D or 3D array")
    x, y, width, height = box
    if width <= 0 or height <= 0:
        raise ValueError(f"box width and height must be > 0; got {box}")

    crop = image[y : y + height, x : x + width]
    if crop.size == 0:
        raise ValueError(f"box {box} is outside image bounds")

    return pytesseract.image_to_string(crop).strip()
