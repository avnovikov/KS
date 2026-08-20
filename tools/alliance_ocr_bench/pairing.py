"""Member list pairing helpers ported from alliance scan_70."""

from __future__ import annotations

import re

POWER_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,2})?)\s*[Mm]$")
SKIP_NAMES = {
    "r1",
    "r2",
    "r3",
    "r4",
    "r5",
    "rs",
    "ra",
    "council",
    "gen",
    "i",
    "ii",
    "iii",
    "lv",
    "lv.",
    "members",
    "alliance",
    "alliance members",
    "alliance info",
    "sleeping",
    "gen i",
    "gen ii",
    "contact",
    "apply",
    "leader",
    "language",
    "power",
    "event",
    "schedule",
    "lieutenant",
    "active",
    "inactive",
    "bartender",
    "vip",
    "bar",
    "lounge",
}


def parse_power(text: str) -> float | None:
    compact = text.replace(" ", "").replace(",", "")
    match = POWER_RE.match(compact)
    if not match:
        return None
    raw = match.group(1)
    value = float(raw)
    if "." not in raw and 100 <= value <= 999:
        value = value / 10.0
    return value


def is_name(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 2:
        return False
    if cleaned.lower() in SKIP_NAMES:
        return False
    if parse_power(cleaned) is not None:
        return False
    if re.fullmatch(r"Lv\.?\s*\d{1,2}", cleaned, re.I):
        return False
    if re.fullmatch(r"\d+", cleaned):
        return False
    return True


def pair_members(
    hits: list[tuple[float, float, str, float]],
    max_dx: float = 240,
    min_dy: float = 8,
    max_dy: float = 100,
) -> list[dict]:
    powers: list[tuple[float, float, float, str]] = []
    names: list[tuple[float, float, str]] = []
    for cx, cy, text, conf in hits:
        power = parse_power(text)
        if power is not None:
            powers.append((cx, cy, power, text))
        elif is_name(text):
            names.append((cx, cy, text))
    members: list[dict] = []
    used: set[int] = set()
    for px, py, power, _raw in powers:
        best = None
        best_dist = 1e9
        for i, (nx, ny, name) in enumerate(names):
            if i in used or ny > py + 10 or abs(nx - px) > max_dx:
                continue
            dy = py - ny
            if dy < min_dy or dy > max_dy:
                continue
            dist = abs(nx - px) + dy
            if dist < best_dist:
                best_dist = dist
                best = i
        if best is None:
            continue
        used.add(best)
        members.append({"name": names[best][2], "power": power})
    return members
