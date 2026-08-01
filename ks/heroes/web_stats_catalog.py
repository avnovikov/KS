"""Fetch ungared hero stats catalog from kingshotdata.com."""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import certifi

SOURCE = "https://kingshotdata.com"
CATEGORY_URL = f"{SOURCE}/category/heroes/"
USER_AGENT = "KS-heroes-catalog/1.0 (+local research; respect robots)"

_SKIP_SLUGS = {
    "generation-1-heroes",
    "generation-2-heroes",
    "generation-3-heroes",
    "generation-4-heroes",
    "generation-5-heroes",
    "generation-6-heroes",
    "generation-7-heroes",
}


@dataclass
class StarRow:
    star: int
    expedition_attack_pct: float
    expedition_defense_pct: float
    shards_to_next: int


@dataclass
class CatalogSkill:
    section: str  # conquest | expedition | exclusive_conquest | exclusive_expedition
    name: str
    description: str | None = None
    upgrade_preview: str | None = None
    levels: list[float] = field(default_factory=list)


@dataclass
class HeroWebStats:
    name: str
    slug: str
    source_url: str
    troop: str | None = None
    rarity: str | None = None
    generation: int | None = None
    conquest: dict[str, int] = field(default_factory=dict)
    expedition: dict[str, float] = field(default_factory=dict)
    star_table: list[StarRow] = field(default_factory=list)
    skills: list[CatalogSkill] = field(default_factory=list)
    exclusive_weapon: str | None = None
    scraped_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slug": self.slug,
            "source_url": self.source_url,
            "troop": self.troop,
            "rarity": self.rarity,
            "generation": self.generation,
            "conquest": dict(self.conquest),
            "expedition": dict(self.expedition),
            "star_table": [asdict(r) for r in self.star_table],
            "skills": [asdict(s) for s in self.skills],
            "exclusive_weapon": self.exclusive_weapon,
            "scraped_at": self.scraped_at,
        }


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def fetch_html(url: str, *, timeout: float = 60.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc


def html_to_text(html: str) -> str:
    clean = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    clean = re.sub(r"<style[\s\S]*?</style>", "", clean, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", clean)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def discover_hero_slugs(category_html: str | None = None) -> list[str]:
    html = category_html if category_html is not None else fetch_html(CATEGORY_URL)
    slugs = sorted(
        {
            s.lower()
            for s in re.findall(r"/heroes/([a-z0-9\-]+)/?", html, flags=re.I)
            if s.lower() not in _SKIP_SLUGS and "generation" not in s.lower()
        }
    )
    if not slugs:
        raise RuntimeError("no hero slugs found on kingshotdata category page")
    return slugs


def _parse_int(raw: str) -> int:
    return int(raw.replace(",", "").replace(" ", ""))


def _parse_pct(raw: str) -> float:
    return float(raw.replace("%", "").replace(",", "").strip())


def _match_meta(text: str) -> tuple[str | None, str | None, int | None]:
    troop = None
    rarity = None
    generation = None
    m = re.search(
        r"\b(Infantry|Cavalry|Archer|Archers)\b\s*hero",
        text,
        flags=re.I,
    )
    if m:
        troop = m.group(1).lower()
        if troop == "archer":
            troop = "archers"
    m = re.search(r"\b(Legendary|Epic|Rare|Mythic)\b", text, flags=re.I)
    if m:
        rarity = m.group(1).lower()
        if rarity == "mythic":
            rarity = "legendary"
    m = re.search(r"\bGen(?:eration)?\s*(\d+)\b", text, flags=re.I)
    if m:
        generation = int(m.group(1))
    return troop, rarity, generation


def _parse_labeled_block(
    text: str, start_marker: str, labels: tuple[str, ...]
) -> dict[str, float]:
    """Parse Label\\nValue pairs after start_marker until a blank structural break."""
    idx = text.lower().find(start_marker.lower())
    if idx < 0:
        return {}
    chunk = text[idx : idx + 1200]
    out: dict[str, float] = {}
    for label in labels:
        m = re.search(
            rf"{re.escape(label)}\s*\n\s*([+\-]?[\d,]+\.?\d*%?)",
            chunk,
            flags=re.I,
        )
        if not m:
            continue
        raw = m.group(1)
        key = label
        if raw.endswith("%") or raw.startswith("+") or raw.startswith("-"):
            out[key] = _parse_pct(raw)
        else:
            out[key] = float(_parse_int(raw))
    return out


def _parse_star_table(text: str) -> list[StarRow]:
    idx = text.lower().find("star\nexp. atk%")
    if idx < 0:
        idx = text.lower().find("star\nexp.")
    if idx < 0:
        return []
    chunk = text[idx : idx + 4000]
    rows: list[StarRow] = []
    for m in re.finditer(
        r"\n(\d{1,2})\n([\d.]+)%\n([\d.]+)%\n(\d+)\b",
        chunk,
    ):
        star = int(m.group(1))
        if star < 1 or star > 40:
            continue
        rows.append(
            StarRow(
                star=star,
                expedition_attack_pct=float(m.group(2)),
                expedition_defense_pct=float(m.group(3)),
                shards_to_next=int(m.group(4)),
            )
        )
    # de-dupe by star keeping first
    by_star: dict[int, StarRow] = {}
    for row in rows:
        by_star.setdefault(row.star, row)
    return [by_star[k] for k in sorted(by_star)]


def _parse_skills(text: str) -> list[CatalogSkill]:
    skills: list[CatalogSkill] = []
    # Sections tagged as Conquest\nName or Expedition\nName after skills headers
    pattern = re.compile(
        r"\n(Conquest|Expedition|Exclusive Conquest|Exclusive Expedition)\n"
        r"([A-Za-z][A-Za-z0-9'’ \-]{1,60})\n"
        r"([\s\S]*?)(?=\n(?:Conquest|Expedition|Exclusive Conquest|Exclusive Expedition|Exclusive Weapon|Stats progression|How to unlock)\n|\Z)",
        flags=re.I,
    )
    for m in pattern.finditer(text):
        section = m.group(1).strip().lower().replace(" ", "_")
        name = m.group(2).strip()
        body = m.group(3).strip()
        if name.lower() in {"stats", "skills"}:
            continue
        preview_m = re.search(
            r"([A-Za-z][A-Za-z /']+:)\s*\n?\s*((?:\d+\.?\d*%?\s*/\s*)+\d+\.?\d*%?)",
            body,
        )
        upgrade = None
        levels: list[float] = []
        if preview_m:
            upgrade = f"{preview_m.group(1).strip()} {preview_m.group(2).strip()}"
            levels = [
                float(x)
                for x in re.findall(r"(\d+\.?\d*)%?", preview_m.group(2))
            ]
        desc = body.split("\n")[0].strip() if body else None
        skills.append(
            CatalogSkill(
                section=section,
                name=name,
                description=desc,
                upgrade_preview=upgrade,
                levels=levels,
            )
        )
    return skills


def parse_hero_page(html: str, *, slug: str, url: str) -> HeroWebStats:
    text = html_to_text(html)
    title_m = re.search(r"^([A-Za-z][A-Za-z0-9'’ &\-]{1,40})\n", text)
    name = title_m.group(1).strip() if title_m else slug.replace("-", " ").title()
    # Prefer H1-like: first line after possible breadcrumbs often is name
    h1 = re.search(rf"<h1[^>]*>\s*([^<]+?)\s*</h1>", html, flags=re.I)
    if h1:
        name = re.sub(r"\s+", " ", h1.group(1)).strip()

    troop, rarity, generation = _match_meta(text)
    conquest_raw = _parse_labeled_block(
        text,
        "Conquest stats",
        ("Hero Attack", "Hero Defense", "Hero Health"),
    )
    # Also try Max Level Stats block (some pages)
    max_raw = _parse_labeled_block(
        text,
        "Max Level Stats",
        (
            "Power",
            "Hero Attack",
            "Hero Defense",
            "Hero Health",
            "Escort Attack",
            "Escort Defense",
            "Escort Health",
        ),
    )
    conquest: dict[str, int] = {}
    for src in (conquest_raw, max_raw):
        for k, v in src.items():
            if k == "Power":
                continue
            conquest[k] = int(v)

    expedition_raw = _parse_labeled_block(
        text,
        "Expedition stats",
        (
            "Infantry Attack",
            "Infantry Defense",
            "Cavalry Attack",
            "Cavalry Defense",
            "Archer Attack",
            "Archer Defense",
            "Infantry Lethality",
            "Infantry Health",
            "Cavalry Lethality",
            "Cavalry Health",
            "Archer Lethality",
            "Archer Health",
        ),
    )
    expedition = {k: float(v) for k, v in expedition_raw.items()}

    weapon = None
    wm = re.search(r"Exclusive weapon\s*\n\s*([^\n]+)", text, flags=re.I)
    if wm:
        weapon = wm.group(1).strip()
    else:
        wm = re.search(r"Exclusive\n([A-Za-z][^\n]{2,40})", text)
        if wm and "weapon" not in wm.group(1).lower():
            weapon = wm.group(1).strip()

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return HeroWebStats(
        name=name,
        slug=slug,
        source_url=url,
        troop=troop,
        rarity=rarity,
        generation=generation,
        conquest=conquest,
        expedition=expedition,
        star_table=_parse_star_table(text),
        skills=_parse_skills(text),
        exclusive_weapon=weapon,
        scraped_at=now,
    )


def scrape_hero_slug(slug: str, *, pause_s: float = 0.35) -> HeroWebStats:
    url = f"{SOURCE}/heroes/{slug}/"
    html = fetch_html(url)
    if pause_s > 0:
        time.sleep(pause_s)
    return parse_hero_page(html, slug=slug, url=url)


def scrape_catalog(
    *,
    slugs: list[str] | None = None,
    pause_s: float = 0.35,
) -> dict[str, Any]:
    found = slugs if slugs is not None else discover_hero_slugs()
    heroes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for slug in found:
        try:
            heroes.append(scrape_hero_slug(slug, pause_s=pause_s).to_dict())
            print(f"ok {slug}")
        except Exception as exc:  # noqa: BLE001 — collect and continue
            print(f"fail {slug}: {exc}")
            errors.append({"slug": slug, "error": str(exc)})
    return {
        "_meta": {
            "source": SOURCE,
            "category": CATEGORY_URL,
            "scraped_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "count": len(heroes),
            "errors": errors,
            "note": "Ungared max / published stats from kingshotdata hero pages.",
        },
        "heroes": heroes,
    }


def write_catalog(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
