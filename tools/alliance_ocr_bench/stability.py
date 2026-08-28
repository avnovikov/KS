"""Name stability helpers ported from alliance scan export rules."""

from __future__ import annotations

import re

OCR_MERGE_POWER_GAP = 0.5
LEVENSHTEIN_MAX_POWER_GAP = 5.0
SHORT_NAME_EDIT_LIMIT = 1
LONG_NAME_EDIT_LIMIT = 2
LONG_NAME_MIN_LEN = 8


def normalize_name(name: str) -> str:
    cleaned = name.lower().strip()
    return re.sub(r"[^a-z0-9\u00c0-\u024f]+", "", cleaned)


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, left_ch in enumerate(left, 1):
        current = [i]
        for j, right_ch in enumerate(right, 1):
            insert = previous[j] + 1
            delete = current[j - 1] + 1
            substitute = previous[j - 1] + (left_ch != right_ch)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def ocr_edit_distance(left: str, right: str) -> int | None:
    """Return a small Levenshtein distance if this looks like OCR drift, else None."""
    a = normalize_name(left)
    b = normalize_name(right)
    if not a or not b:
        return None
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return None
    distance = levenshtein(a, b)
    longest = max(len(a), len(b))
    if longest < 5:
        return None
    limit = SHORT_NAME_EDIT_LIMIT if longest < LONG_NAME_MIN_LEN else LONG_NAME_EDIT_LIMIT
    if distance <= limit:
        return distance
    return None
