from __future__ import annotations

import re

from ks.heroes.models import HeroStats, SkillRecord

_INT_RE = re.compile(r"-?\d[\d,]*")
_PERCENT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")
_CONQUEST_LINE = re.compile(
    r"^\s*(Hero Attack|Hero Defense|Hero Health|Escort Attack|Escort Defense|Escort Health)"
    r"\s*[:=]?\s*([\d,]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_EXPEDITION_LINE = re.compile(
    r"^\s*([A-Za-z][A-Za-z ]+?)\s*[:=]?\s*\+?\s*([\d.]+)\s*%\s*$",
    re.MULTILINE,
)
_SKILL_TITLE = re.compile(
    r"^\s*(.+?)\s+Lv\.?\s*(\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RARITY_RE = re.compile(r"\b(UR|SSR|SR|R)\b", re.IGNORECASE)


def parse_int(text: str) -> int | None:
    """Extract the first integer from OCR text (commas allowed)."""
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")
    match = _INT_RE.search(text.replace(" ", ""))
    if not match:
        match = _INT_RE.search(text)
    if not match:
        return None
    return int(match.group(0).replace(",", ""))


def parse_power(text: str) -> int | None:
    """Hero power under the name — first integer in the crop."""
    return parse_int(text)


def parse_percent(text: str) -> float | None:
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")
    match = _PERCENT_RE.search(text)
    if not match:
        return None
    return float(match.group(1))


def parse_rarity(text: str) -> str | None:
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")
    match = _RARITY_RE.search(text)
    return match.group(1).upper() if match else None


def clean_name(text: str) -> str | None:
    """Return a usable hero name or None if the crop looks empty."""
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")
    # Keep letters / hyphen / apostrophe; drop OCR junk.
    cleaned = re.sub(r"[^A-Za-z\-'\s]+", " ", text)
    name = " ".join(cleaned.split()).strip()
    if len(name) < 2:
        return None
    if name.isdigit():
        return None
    # Prefer Title Case tokens for stable dedupe keys.
    return " ".join(part.capitalize() for part in name.split())


def _parse_conquest_exact(text: str) -> dict[str, int]:
    """Strict ``Hero Attack 1,619`` style conquest lines."""
    conquest: dict[str, int] = {}
    for match in _CONQUEST_LINE.finditer(text):
        label = " ".join(w.capitalize() for w in match.group(1).split())
        conquest[label] = int(match.group(2).replace(",", ""))
    return conquest


def _augment_conquest_fuzzy(conquest: dict[str, int], text: str) -> None:
    """Recover conquest stats when OCR drops leading letters ("ero Attack").

    Walks lines top-to-bottom, tracking whether we're still in the Hero
    section or have crossed into Escort, and stops once Expedition starts.
    Mutates ``conquest`` in place, preferring already-present exact matches.
    """
    escort_mode = False
    for line in text.splitlines():
        low = line.lower().strip()
        if not low:
            continue
        if "exped" in low or "edition" in low:
            break
        if "escort" in low or low.startswith("scort") or low.startswith("ort "):
            escort_mode = True
        match = re.search(
            r"(?:ero|scort|ort|hero|escort)?\s*(Attack|Defense|Health)\s*([\d,]+)",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue
        kind = match.group(1).title()
        value = int(match.group(2).replace(",", ""))
        prefix = "Escort" if escort_mode else "Hero"
        key = f"{prefix} {kind}"
        if key in conquest and prefix == "Hero":
            key = f"Escort {kind}"
        conquest.setdefault(key, value)
        if kind == "Health" and prefix == "Hero":
            escort_mode = True


def _expedition_region(text: str) -> str:
    """Slice ``text`` starting at the Expedition section header, if present."""
    lower = text.lower()
    exp_idx = lower.find("expedition")
    if exp_idx < 0:
        exp_idx = lower.find("edition")  # truncated "Expedition"
    return text[exp_idx:] if exp_idx >= 0 else text


def _parse_expedition_exact(exp_region: str) -> dict[str, float]:
    expedition: dict[str, float] = {}
    for match in _EXPEDITION_LINE.finditer(exp_region):
        label = " ".join(w.capitalize() for w in match.group(1).split())
        if label.lower() in {"hero stats", "conquest", "expedition", "edition"}:
            continue
        expedition[label] = float(match.group(2))
    return expedition


def _augment_expedition_fuzzy(expedition: dict[str, float], exp_region: str) -> None:
    """Recover percent lines like "jalry Attack +101.37%" with OCR typos.

    Mutates ``expedition`` in place, preferring already-present exact matches.
    """
    for match in re.finditer(
        r"([A-Za-z][A-Za-z ]{2,40}?)\s*\+?\s*([\d.]+)\s*%",
        exp_region,
    ):
        label = " ".join(w.capitalize() for w in match.group(1).split())
        low = label.lower()
        if low in {"hero stats", "conquest", "expedition", "upgrade preview"}:
            continue
        # Repair common OCR truncations for cavalry lines
        if "alry" in low or "cavalry" in low or "jalry" in low:
            kind = label.split()[-1] if " " in label else label
            label = f"Cavalry {kind.capitalize()}"
        expedition.setdefault(label, float(match.group(2)))


def parse_stats_panel(text: str) -> HeroStats:
    """Parse the Hero Stats popup OCR dump into conquest/expedition maps."""
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")

    conquest = _parse_conquest_exact(text)
    if len(conquest) < 6:
        _augment_conquest_fuzzy(conquest, text)

    exp_region = _expedition_region(text)
    expedition = _parse_expedition_exact(exp_region)
    if len(expedition) < 2:
        _augment_expedition_fuzzy(expedition, exp_region)

    return HeroStats(conquest=conquest, expedition=expedition, raw_text=text)


def _validate_skill_panel_args(
    text: str, slot: int, current_bonus: float | None
) -> None:
    if not isinstance(text, str):
        raise ValueError(f"text must be a string; got {type(text).__name__}")
    if slot < 0:
        raise ValueError(f"slot must be >= 0; got {slot}")
    if current_bonus is not None and not (1.0 <= float(current_bonus) <= 400.0):
        raise ValueError(
            f"current_bonus must be in [1, 400] when set; got {current_bonus}"
        )


def _parse_skill_title(text: str) -> tuple[str | None, int | None]:
    title_match = _SKILL_TITLE.search(text)
    if not title_match:
        return None, None
    return title_match.group(1).strip(), int(title_match.group(2))


def _parse_skill_body(text: str) -> tuple[str | None, str | None]:
    """Pick the description line and the upgrade-preview ladder line.

    The upgrade preview is the first line with both ``%`` and ``/`` (e.g.
    ``8%/16%/24%``); the description is the first sufficiently long
    non-title line.
    """
    description: str | None = None
    upgrade_preview: str | None = None
    for line in (ln.strip() for ln in text.splitlines() if ln.strip()):
        if _SKILL_TITLE.match(line):
            continue
        if "%" in line and "/" in line and upgrade_preview is None:
            upgrade_preview = line
            continue
        if description is None and len(line) > 12:
            description = line
    return description, upgrade_preview


def parse_skill_panel(
    text: str,
    *,
    slot: int,
    current_bonus: float | None = None,
) -> SkillRecord:
    """Parse a skill detail panel OCR dump.

    ``current_bonus`` is the teal/green highlighted percent from the panel
    (pass through from ``extract_teal_current_percent``).
    """
    _validate_skill_panel_args(text, slot, current_bonus)

    name, level = _parse_skill_title(text)
    description, upgrade_preview = _parse_skill_body(text)

    return SkillRecord(
        slot=slot,
        name=name,
        level=level,
        description=description,
        upgrade_preview=upgrade_preview,
        current_bonus=float(current_bonus) if current_bonus is not None else None,
        raw_text=text,
    )
