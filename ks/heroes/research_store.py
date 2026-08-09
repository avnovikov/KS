"""Persist Academy research troop % bonuses as YAML under ``out_dir``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from ks.heroes.research_models import ResearchBonuses

_FILENAME = "research.yaml"


class ResearchStore:
    """Manual research inventory (percent-points per troop type)."""

    def __init__(self, out_dir: Path) -> None:
        if not isinstance(out_dir, Path):
            raise TypeError(f"out_dir must be Path; got {type(out_dir).__name__}")
        self.out_dir = out_dir.expanduser().resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.yaml_path = self.out_dir / _FILENAME
        self._bonuses = ResearchBonuses.empty(
            note=(
                "Manual Academy Battle (+ War Academy) troop % — "
                "percent-points, same units as battle-report bonuses."
            )
        )
        self._load()

    def _load(self) -> None:
        if not self.yaml_path.is_file():
            self.flush()
            return
        raw = yaml.safe_load(self.yaml_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, Mapping):
            raise ValueError(f"{self.yaml_path} must be a YAML mapping")
        self._bonuses = ResearchBonuses.from_dict(raw)

    def bonuses(self) -> ResearchBonuses:
        return self._bonuses

    def replace(self, bonuses: ResearchBonuses) -> ResearchBonuses:
        if not isinstance(bonuses, ResearchBonuses):
            raise TypeError(
                f"bonuses must be ResearchBonuses; got {type(bonuses).__name__}"
            )
        self._bonuses = bonuses
        self.flush()
        return self._bonuses

    def update_from_dict(self, raw: Mapping[str, Any]) -> ResearchBonuses:
        """Merge a partial or full payload into the stored bonuses."""
        if not isinstance(raw, Mapping):
            raise TypeError(f"update payload must be mapping; got {type(raw).__name__}")
        base = self._bonuses.to_dict()
        if "note" in raw:
            base["note"] = str(raw.get("note") or "")
        incoming_troops = raw.get("troops")
        if isinstance(incoming_troops, Mapping):
            for troop, row in incoming_troops.items():
                if troop not in base["troops"]:
                    raise KeyError(f"unknown troop type {troop!r}")
                if not isinstance(row, Mapping):
                    raise TypeError(
                        f"troops.{troop} must be a mapping; got {type(row).__name__}"
                    )
                cur = dict(base["troops"][troop])
                for key in ("attack_pct", "defense_pct", "lethality_pct", "health_pct"):
                    if key in row:
                        cur[key] = float(row[key])
                base["troops"][troop] = cur
        else:
            # Allow top-level troop keys.
            for troop in list(base["troops"]):
                if troop in raw and isinstance(raw[troop], Mapping):
                    cur = dict(base["troops"][troop])
                    for key in (
                        "attack_pct",
                        "defense_pct",
                        "lethality_pct",
                        "health_pct",
                    ):
                        if key in raw[troop]:
                            cur[key] = float(raw[troop][key])
                    base["troops"][troop] = cur
        return self.replace(ResearchBonuses.from_dict(base))

    def flush(self) -> None:
        payload = self._bonuses.to_dict()
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        self.yaml_path.write_text(text, encoding="utf-8")

    def summary(self) -> dict[str, Any]:
        b = self._bonuses
        return {
            "path": str(self.yaml_path),
            "note": b.note,
            "bonuses": b.to_dict(),
            "attack_pct": b.attack_pct(),
            "defense_pct": b.defense_pct(),
            "lethality_pct": b.lethality_pct(),
            "health_pct": b.health_pct(),
        }


__all__ = ["ResearchStore"]
