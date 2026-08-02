"""Parse Gear Details OCR text into GearRecord fields."""

from __future__ import annotations

import re

from ks.heroes.gear_models import GearRecord, GearStats, make_piece_id
from ks.heroes.parse import parse_int

_RARITY_MAP = {
    "grey": "grey",
    "gray": "grey",
    "common": "grey",
    "green": "green",
    "uncommon": "green",
    "blue": "blue",
    "rare": "blue",
    "purple": "purple",
    "epic": "epic",
    "gold": "mythic",
    "mythic": "mythic",
    "red": "red",
}

_SLOT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(helmet|armet|faceplate|helm)\b", re.I), "helmet"),
    (
        re.compile(r"\b(chest|armor|armour|cuirass|shroud|plate|leatherwear|breastplate)\b", re.I),
        "chest",
    ),
    (re.compile(r"\b(gloves?|gauntlets?|grips|bracers?)\b", re.I), "gloves"),
    (re.compile(r"\b(boots?|greaves|riders?)\b", re.I), "boots"),
]

_TROOP_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\binfantry\b", re.I), "infantry"),
    (re.compile(r"\bcavalry\b", re.I), "cavalry"),
    (re.compile(r"\b(archers?|marksman|ranged)\b", re.I), "archers"),
]

_ENHANCEMENT_RE = re.compile(
    r"(?:enhancement\s*(?:lv\.?|level)?\s*|[+]?\s*)(\d{1,3})\b",
    re.I,
)
# Enhancement badge "+30" — never expedition "+30.60%" / "+30%" / "+3" prefixes.
_PLUS_LEVEL_RE = re.compile(r"\+(\d{1,3})(?!\d)(?!\.\d)(?!\s*%)")
_MASTERY_RE = re.compile(
    r"(?:mastery\s*(?:lv\.?|level)?\s*[+]?\s*|lv\.?\s*)(\d{1,2})\b",
    re.I,
)
_RARITY_RE = re.compile(
    r"\b(grey|gray|common|green|uncommon|blue|rare|purple|epic|gold|mythic|red)\b",
    re.I,
)
_NAME_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z' \-]{2,40})\s*$",
    re.MULTILINE,
)
_NAME_TITLE_RE = re.compile(
    r"([A-Z][A-Za-z]+(?:'[sd])?(?:[ \-][A-Z][A-Za-z]+)+)"
)
_CONQUEST_LINE = re.compile(
    r"(Hero Attack|Hero Defense|Hero Health|Escort Attack|Escort Defense|Escort Health)"
    r"\s*[:=]?\s*([\d,]+)",
    re.IGNORECASE,
)
_EXPEDITION_LINE = re.compile(
    r"((?:Infantry|Cavalry|Archer|Archers)[A-Za-z ]*?)"
    r"\s*[:=]?\s*\+?\s*([\d.]+)\s*%",
    re.IGNORECASE,
)
_SKIP_NAME = {
    "gear details",
    "geardetails",
    "geardetails os",
    "conquest stats",
    "expedition stats",
    "troop mastery",
    "mastery forging",
    "enhance",
    "unequip",
    "equip",
    "reforge",
    "mythic",
    "epic",
    "rare",
    "gold",
    "purple",
    "blue",
    "green",
    "red",
    # Expedition/conquest stat labels that OCR may surface as candidate names.
    "hero attack",
    "hero defense",
    "hero health",
    "escort attack",
    "escort defense",
    "escort health",
    "infantry lethality",
    "infantry attack",
    "infantry defense",
    "infantry health",
    "cavalry lethality",
    "cavalry attack",
    "cavalry defense",
    "cavalry health",
    "archer lethality",
    "archers lethality",
    "archer attack",
    "archer defense",
    "archer health",
}


def parse_gear_detail(text: str, *, page: int, index: int) -> GearRecord:
    if not isinstance(text, str):
        raise TypeError(f"text must be str; got {type(text).__name__}")
    if page < 0 or index < 0:
        raise ValueError(f"page/index must be >= 0; got page={page} index={index}")

    rarity = _parse_rarity(text)
    mastery = _parse_mastery(text)
    troop = _parse_troop(text)
    slot = _parse_slot(text)
    name = _parse_name(text)
    power = _parse_power(text)
    # Infer rarity from power when OCR missed the rarity badge (common on grey pieces).
    if rarity is None and power is not None:
        rarity = _infer_rarity_from_power(power, mastery=mastery)
    enhancement = _resolve_enhancement(text, rarity=rarity, power=power, mastery=mastery)
    equipped = _parse_equipped(text)
    stats = _parse_stats(text)

    if troop is None and stats is not None:
        troop = _troop_from_expedition(stats.expedition)

    # Fallback: derive slot from resolved name when OCR text lacks slot keywords.
    if slot is None and name is not None:
        slot = _parse_slot(name)

    return GearRecord(
        piece_id=make_piece_id(page, index),
        name=name,
        troop_type=troop,
        slot=slot,
        rarity=rarity,
        enhancement_level=enhancement,
        mastery_level=mastery,
        power=power,
        equipped=equipped,
        equipped_hero=None,
        stats=stats,
        raw_text=text,
        inventory_page=page,
        inventory_index=index,
    )


def _parse_rarity(text: str) -> str | None:
    match = _RARITY_RE.search(text)
    if not match:
        return None
    return _RARITY_MAP[match.group(1).lower()]


def _infer_rarity_from_power(power: int, *, mastery: int | None = None) -> str | None:
    """Guess rarity by fitting power against all known curves.

    Score = power_error + 15 * enhancement_level (penalise implausibly high
    enhancement to prefer lower-rarity interpretations for low powers).
    Returns None when no rarity fits within tolerance.
    """
    from ks.heroes.ui.power import _RARITY_LINEAR, compute_gear_power

    best_rarity: str | None = None
    best_score: float = float("inf")
    mast = int(mastery or 0)
    for rarity_key, (intercept, slope) in _RARITY_LINEAR.items():
        if slope == 0:
            continue
        demastered = float(power) / max(1.0 + 0.1 * mast, 1.0)
        enh = int(round((demastered - intercept) / slope))
        if enh < 0 or enh > 200:
            continue
        estimated = compute_gear_power(rarity_key, enh, mast)
        err = abs(estimated - power)
        score = err + 15 * enh
        if score < best_score:
            best_score = score
            best_rarity = rarity_key
    return best_rarity


def _reject_power_prefix_badges(plus_vals: list[int], power: int | None) -> list[int]:
    """Remove +N values that look like a power prefix rather than enhancement.

    Only applies when power is a plausible gear power (>= 1000). If the power
    OCR only captured a small fallback integer (e.g. 5 from "+5"), the filter
    is skipped to avoid removing legitimate enhancement badges.
    """
    if power is None or power < 1000 or not plus_vals:
        return plus_vals
    power_digits = len(str(power))
    return [v for v in plus_vals if len(str(v)) < power_digits]


def _detail_header(text: str) -> str:
    """Text above Conquest/Expedition — name / power / icon badge live here."""
    return re.split(
        r"conquest\s+stats|expedition\s+stats",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]


def _enhancement_search_text(text: str) -> str:
    """Detail-phase text where +N means enhancement — not expedition +N.NN% lines.

    Keeps the header (icon badge / glued title) and footer action lines
    (``Enhance`` / bare ``+30``) while dropping percent stats.
    """
    header = _detail_header(text)
    footer_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\+\s*\d+(?:\.\d+)?\s*%", stripped):
            continue
        lower = stripped.lower()
        if lower.startswith(
            ("enhance", "mastery forging", "reforge", "unequip", "equip")
        ) or re.fullmatch(r"\+?\d{1,3}", stripped) or re.fullmatch(
            r"lv\.?\s*\d{1,2}", stripped, flags=re.I
        ):
            footer_lines.append(stripped)
    return header + "\n" + "\n".join(footer_lines)


def _enhancement_from_plus_badge(search: str, power: int | None) -> int | None:
    plus_vals = [int(m.group(1)) for m in _PLUS_LEVEL_RE.finditer(search)]
    plus_vals = [v for v in plus_vals if 0 <= v <= 200]
    plus_vals = _reject_power_prefix_badges(plus_vals, power)
    if not plus_vals:
        return None
    # Badge values are usually the largest +N that isn't a tiny OCR speck.
    return max(plus_vals)


def _enhancement_from_known_title_prefix(search: str) -> int | None:
    """Digits immediately before a known gear title: "Qt23 Crusader…"."""
    lower_search = search.lower().replace("'", "")
    for known in _KNOWN_GEAR_NAMES:
        key = known.lower().replace("'", "")
        idx = lower_search.find(key)
        if idx <= 0:
            continue
        prefix = search[max(0, idx - 6) : idx]
        m = re.search(r"(\d{1,3})\s*$", prefix)
        if m:
            level = int(m.group(1))
            if 0 <= level <= 200:
                return level
    return None


def _enhancement_from_glued_title(text: str) -> int | None:
    """OCR often glues enhancement onto the title: "aer30 Judicator's Armet"."""
    glued = re.search(
        r"(?<![0-9.,])(\d{1,3})\s+([A-Za-z][A-Za-z']+(?:\s+[A-Za-z][A-Za-z']+)+)",
        _detail_header(text),
    )
    if not glued:
        return None
    title = glued.group(2).lower()
    level = int(glued.group(1))
    excluded_words = ("stat", "mastery", "detail", "hero", "escort", "stonewall")
    if 0 <= level <= 200 and not any(word in title for word in excluded_words):
        return level
    return None


def _enhancement_from_explicit_label(search: str) -> int | None:
    explicit = re.search(
        r"enhancement\s*(?:lv\.?|level)?\s*[+]?\s*(\d{1,3})\b",
        search,
        re.I,
    )
    return int(explicit.group(1)) if explicit else None


def _parse_enhancement(text: str, *, power: int | None = None) -> int | None:
    # Detail-phase only: header badge / Enhance footer — never expedition %.
    search = _enhancement_search_text(text)

    for finder in (
        lambda: _enhancement_from_plus_badge(search, power),
        lambda: _enhancement_from_known_title_prefix(search),
        lambda: _enhancement_from_glued_title(text),
        lambda: _enhancement_from_explicit_label(search),
    ):
        level = finder()
        if level is not None:
            return level
    return None


def _resolve_enhancement(
    text: str,
    *,
    rarity: str | None,
    power: int | None,
    mastery: int | None,
) -> int | None:
    """Detail-phase OCR +N, validated against power when both are available.

    Noisy detail OCR often invents digits (escort stats, partial badges). When
    the power curve disagrees by more than 2 levels, trust the curve.
    """
    from ks.heroes.ui.power import estimate_enhancement_from_power

    ocr_level = _parse_enhancement(text, power=power)
    inferred = estimate_enhancement_from_power(rarity, power, mastery)
    if ocr_level is None:
        return inferred
    if inferred is None:
        return ocr_level
    if abs(ocr_level - inferred) > 2:
        return inferred
    return ocr_level


def _parse_mastery(text: str) -> int | None:
    explicit = re.search(r"mastery\s*(?:lv\.?|level)?\s*[+]?\s*(\d{1,2})\b", text, re.I)
    if explicit:
        return int(explicit.group(1))
    # Standalone Lv. N near gear icon (not Enhancement Level).
    for match in re.finditer(r"\blv\.?\s*(\d{1,2})\b", text, re.I):
        start = max(0, match.start() - 20)
        window = text[start : match.end()].lower()
        if "enhancement" in window:
            continue
        return int(match.group(1))
    return None


def _parse_troop(text: str) -> str | None:
    for pattern, value in _TROOP_PATTERNS:
        if pattern.search(text):
            return value
    return None


def _parse_slot(text: str) -> str | None:
    for pattern, value in _SLOT_PATTERNS:
        if pattern.search(text):
            return value
    return None


_KNOWN_GEAR_NAMES = [
    "Judicator's Armet",
    "Crusader's Armet",
    "Crusader Battle Boots",
    "Crusader Battie Boots",  # OCR typo
    "Praetorian's Gloves",
    "Praetorian's Shroud",
    "Praetorian s Gloves",
    "Berserker's Faceplate",
    "Berserker's Bracers",
    "Berserker's Boots",
    "Windbreaker Leatherwear",
    "Windbreaker Faceplate",
    "Windbreaker Bracers",
    "Windbreaker Boots",
    "Stonewall Greaves",
    "Stonewall Gloves",
    "Stonewall Shroud",
    "Brigader's Gauntlets",
    "Warrior's Helm",
    "Warrior's Shroud",
    "Warrior's Greaves",
    "Cuirassier's Breastplate",
    "Cuirassier's Armet",
    "Guardian's Helm",
    "Stonewall Helm",
]

# Fuzzy OCR fragments that should resolve to a canonical name.
_KNOWN_GEAR_FUZZY: list[tuple[str, str]] = [
    ("ston ll hel", "Stonewall Helm"),
    ("ston wall hel", "Stonewall Helm"),
    ("guardian hel", "Guardian's Helm"),
    ("warriors helm", "Warrior's Helm"),
    ("warriors shroud", "Warrior's Shroud"),
    ("warriors greaves", "Warrior's Greaves"),
    ("cuirassier armet", "Cuirassier's Armet"),
]

# Slot hint keywords to prefer title candidates that mention the slot.
_SLOT_HINTS: frozenset[str] = frozenset({
    "helm", "helmet", "armet", "faceplate",
    "chest", "armor", "armour", "shroud", "cuirass", "breastplate", "leatherwear",
    "gloves", "gauntlets", "bracers", "grips",
    "boots", "greaves", "riders",
})


def _match_known_gear_name(lower: str) -> str | None:
    """Fuzzy fragments, then exact known titles embedded in noisy OCR."""
    for fragment, canonical in _KNOWN_GEAR_FUZZY:
        if fragment in lower:
            return canonical

    for known in _KNOWN_GEAR_NAMES:
        key = known.lower().replace("'", "")
        if key in lower:
            if known == "Crusader Battie Boots":
                return "Crusader Battle Boots"
            if known == "Praetorian s Gloves":
                return "Praetorian's Gloves"
            return known.replace(" s ", "'s ") if " s " in known else known
    return None


def _match_split_title(lower: str) -> str | None:
    """OCR often splits titles across lines: "Berserker's B" + "Bracers"."""
    if "berserker" in lower and "bracer" in lower:
        return "Berserker's Bracers"
    if "cuirassier" in lower and "breast" in lower:
        return "Cuirassier's Breastplate"
    if "cuirassier" in lower and "armet" in lower:
        return "Cuirassier's Armet"
    return None


def _is_skippable_name_candidate(candidate: str) -> bool:
    lower = candidate.lower()
    return lower in _SKIP_NAME or "detail" in lower or any(ch.isdigit() for ch in candidate)


def _title_case_name_candidates(text: str) -> list[str]:
    """Multi-word Title Case candidates, slot-hinted ones sorted first."""
    candidates = [
        " ".join(match.group(1).split()).strip()
        for match in _NAME_TITLE_RE.finditer(text)
    ]
    candidates = [c for c in candidates if not _is_skippable_name_candidate(c)]

    def _slot_score(c: str) -> int:
        cl = c.lower()
        return 0 if any(h in cl for h in _SLOT_HINTS) else 1

    candidates.sort(key=_slot_score)
    return candidates


def _fallback_name_candidate(text: str) -> str | None:
    """Last-resort single-line name match requiring an apostrophe or space."""
    for match in _NAME_RE.finditer(text):
        candidate = " ".join(match.group(1).split()).strip()
        if _is_skippable_name_candidate(candidate):
            continue
        if candidate == candidate.lower():
            continue
        if "'" in candidate or " " in candidate:
            return candidate
    return None


def _parse_name(text: str) -> str | None:
    lower = text.lower().replace("'", "")

    known = _match_known_gear_name(lower)
    if known is not None:
        return known

    split_title = _match_split_title(lower)
    if split_title is not None:
        return split_title

    title_candidates = _title_case_name_candidates(text)
    if title_candidates:
        return title_candidates[0]

    return _fallback_name_candidate(text)


def _parse_power(text: str) -> int | None:
    # Combat power lives in the header above Conquest/Expedition sections.
    header = re.split(r"conquest\s+stats|expedition\s+stats", text, maxsplit=1, flags=re.I)[
        0
    ]
    matches = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3}){1,2})(?!\d)", header)
    if not matches:
        matches = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3}){1,2})(?!\d)", text)
    if not matches:
        return parse_int(header)
    values = [int(m.replace(",", "")) for m in matches]
    plausible = [v for v in values if 100 <= v <= 9_999_999]
    if not plausible:
        return values[0]
    # OCR sometimes prepends a digit (98,550 → 798,550 or 18,360 → 218,360).
    # Never strip a leading 1 from 1xx,xxx values like 152,100.
    cleaned: list[int] = []
    for value in plausible:
        s = str(value)
        if len(s) >= 6 and s[0] in "23456789":
            trimmed = int(s[1:])
            if 10_000 <= trimmed <= 999_999:
                cleaned.append(trimmed)
                continue
        cleaned.append(value)
    # Header usually has a single power number — take the largest cleaned value.
    return max(cleaned) if cleaned else max(plausible)


def _parse_equipped(text: str) -> bool | None:
    lower = text.lower()
    if "unequip" in lower or "nequip" in lower or "uneaui" in lower:
        return True
    if re.search(r"\bequip\b", lower):
        return False
    if "equipped" in lower:
        return True
    return None


def _parse_stats(text: str) -> GearStats | None:
    conquest: dict[str, int] = {}
    for match in _CONQUEST_LINE.finditer(text):
        label = " ".join(w.capitalize() for w in match.group(1).split())
        conquest[label] = int(match.group(2).replace(",", ""))

    expedition: dict[str, float] = {}
    for match in _EXPEDITION_LINE.finditer(text):
        label = " ".join(w.capitalize() for w in match.group(1).split())
        label = label.replace("Archers ", "Archer ")
        expedition[label] = float(match.group(2))

    if not conquest and not expedition:
        return None

    attack = _expedition_stat(expedition, "attack")
    defense = _expedition_stat(expedition, "defense")
    health = _expedition_stat(expedition, "health")
    lethality = _expedition_stat(expedition, "lethality")
    return GearStats(
        conquest=conquest,
        expedition=expedition,
        attack=attack,
        defense=defense,
        health=health,
        lethality=lethality,
        raw_text=text,
    )


def _expedition_stat(expedition: dict[str, float], key: str) -> float | None:
    key_l = key.lower()
    for label, value in expedition.items():
        if key_l in label.lower():
            return value
    return None


def _troop_from_expedition(expedition: dict[str, float]) -> str | None:
    for label in expedition:
        lower = label.lower()
        if "infantry" in lower:
            return "infantry"
        if "cavalry" in lower:
            return "cavalry"
        if "archer" in lower:
            return "archers"
    return None
