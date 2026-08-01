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
# Enhancement badge "+30" — do not match expedition "+30.60%" (or partial +3).
_PLUS_LEVEL_RE = re.compile(r"\+(\d{1,3})(?!\d)(?!\.\d)")
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
}


def parse_gear_detail(text: str, *, page: int, index: int) -> GearRecord:
    if not isinstance(text, str):
        raise TypeError(f"text must be str; got {type(text).__name__}")
    if page < 0 or index < 0:
        raise ValueError(f"page/index must be >= 0; got page={page} index={index}")

    rarity = _parse_rarity(text)
    enhancement = _parse_enhancement(text)
    mastery = _parse_mastery(text)
    troop = _parse_troop(text)
    slot = _parse_slot(text)
    name = _parse_name(text)
    power = _parse_power(text)
    equipped = _parse_equipped(text)
    stats = _parse_stats(text)

    if troop is None and stats is not None:
        troop = _troop_from_expedition(stats.expedition)

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


def _parse_enhancement(text: str) -> int | None:
    # Prefer explicit +N badges (enhancement), never expedition "+30.60%".
    plus_vals = [int(m.group(1)) for m in _PLUS_LEVEL_RE.finditer(text)]
    plus_vals = [v for v in plus_vals if 0 <= v <= 200]
    if plus_vals:
        # Badge values are usually the largest +N that isn't a tiny OCR speck.
        return max(plus_vals)

    # OCR often glues enhancement onto the title: "aer30 Judicator's Armet".
    glued = re.search(
        r"(?<![0-9.,])(\d{2,3})\s+([A-Z][A-Za-z]+(?:'[sd])?(?:\s+[A-Z][A-Za-z]+)+)",
        text,
    )
    if glued:
        title = glued.group(2).lower()
        if "stat" not in title and "mastery" not in title and "detail" not in title:
            return int(glued.group(1))

    explicit = re.search(
        r"enhancement\s*(?:lv\.?|level)?\s*[+]?\s*(\d{1,3})\b",
        text,
        re.I,
    )
    if explicit:
        return int(explicit.group(1))
    return None


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
    "Cuirassier's Breastplate",
]


def _parse_name(text: str) -> str | None:
    # Prefer known gear titles embedded in noisy OCR.
    lower = text.lower().replace("'", "")
    for known in _KNOWN_GEAR_NAMES:
        key = known.lower().replace("'", "")
        if key in lower:
            if known == "Crusader Battie Boots":
                return "Crusader Battle Boots"
            if known == "Praetorian s Gloves":
                return "Praetorian's Gloves"
            return known.replace(" s ", "'s ") if " s " in known else known

    # OCR often splits titles across lines: "Berserker's B" + "Bracers".
    if "berserker" in lower and "bracer" in lower:
        return "Berserker's Bracers"
    if "cuirassier" in lower and "breast" in lower:
        return "Cuirassier's Breastplate"

    # Prefer multi-word Title Case titles (e.g. Judicator's Armet).
    for match in _NAME_TITLE_RE.finditer(text):
        candidate = " ".join(match.group(1).split()).strip()
        if candidate.lower() in _SKIP_NAME:
            continue
        if "detail" in candidate.lower():
            continue
        if any(ch.isdigit() for ch in candidate):
            continue
        return candidate

    for match in _NAME_RE.finditer(text):
        candidate = " ".join(match.group(1).split()).strip()
        if candidate.lower() in _SKIP_NAME:
            continue
        if "detail" in candidate.lower():
            continue
        if any(ch.isdigit() for ch in candidate):
            continue
        if candidate == candidate.lower():
            continue
        if "'" in candidate or " " in candidate:
            return candidate
    return None


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
