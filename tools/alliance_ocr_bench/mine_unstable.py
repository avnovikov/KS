"""Mine unstable OCR name pairs from two alliance listing JSON snapshots."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from tools.alliance_ocr_bench.stability import (
    LEVENSHTEIN_MAX_POWER_GAP,
    normalize_name,
    ocr_edit_distance,
)

_RANK_BUCKETS = ("r5", "r4", "r3", "r2")


def _flatten_players(data: dict) -> list[dict]:
    players: list[dict] = []
    for alliance in data.get("alliances", []) or []:
        tag = str(alliance.get("tag", ""))
        for bucket in _RANK_BUCKETS:
            for player in alliance.get(bucket, []) or []:
                name = str(player.get("name", "")).strip()
                if not name:
                    continue
                players.append(
                    {
                        "tag": tag,
                        "name": name,
                        "power": float(player["power"]),
                        "rank": bucket,
                    }
                )
    return players


def _suggested_shots(tag: str) -> str:
    safe = tag.strip() or "TAG"
    return ",".join(
        [
            f"{safe}-r4-00.png",
            f"{safe}-r3-00.png",
            f"{safe}-members.png",
        ]
    )


def mine_unstable(old: dict, new: dict) -> list[dict]:
    """Return LEVENSHTEIN near-miss pairs within each alliance tag."""
    old_by_tag: dict[str, list[dict]] = {}
    new_by_tag: dict[str, list[dict]] = {}
    for player in _flatten_players(old):
        old_by_tag.setdefault(player["tag"].lower(), []).append(player)
    for player in _flatten_players(new):
        new_by_tag.setdefault(player["tag"].lower(), []).append(player)

    rows: list[dict] = []
    for tag_key in sorted(set(old_by_tag) | set(new_by_tag)):
        old_left = list(old_by_tag.get(tag_key, []))
        new_left = list(new_by_tag.get(tag_key, []))

        used_new: set[int] = set()
        for old_p in list(old_left):
            old_key = normalize_name(old_p["name"])
            hit = None
            for new_p in new_left:
                if id(new_p) in used_new:
                    continue
                if normalize_name(new_p["name"]) == old_key:
                    hit = new_p
                    break
            if hit is None:
                continue
            used_new.add(id(hit))
            old_left.remove(old_p)
            new_left.remove(hit)

        candidates: list[tuple[int, float, dict, dict]] = []
        for old_p in old_left:
            for new_p in new_left:
                distance = ocr_edit_distance(old_p["name"], new_p["name"])
                if distance is None or distance == 0:
                    continue
                gap = abs(old_p["power"] - new_p["power"])
                if gap > LEVENSHTEIN_MAX_POWER_GAP:
                    continue
                candidates.append((distance, gap, old_p, new_p))
        candidates.sort(key=lambda item: (item[0], item[1]))
        used_old: set[int] = set()
        used_new_ids: set[int] = set()
        for distance, _gap, old_p, new_p in candidates:
            if id(old_p) in used_old or id(new_p) in used_new_ids:
                continue
            if old_p not in old_left or new_p not in new_left:
                continue
            used_old.add(id(old_p))
            used_new_ids.add(id(new_p))
            old_left.remove(old_p)
            new_left.remove(new_p)
            tag = old_p["tag"] or new_p["tag"]
            rows.append(
                {
                    "tag": tag,
                    "old_name": old_p["name"],
                    "new_name": new_p["name"],
                    "old_power": old_p["power"],
                    "new_power": new_p["power"],
                    "edit_distance": distance,
                    "match_kind": "LEVENSHTEIN",
                    "suggested_shots": _suggested_shots(tag),
                }
            )
    return rows


def write_candidates_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "tag",
        "old_name",
        "new_name",
        "old_power",
        "new_power",
        "edit_distance",
        "match_kind",
        "suggested_shots",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    old = json.loads(args.old.read_text(encoding="utf-8"))
    new = json.loads(args.new.read_text(encoding="utf-8"))
    rows = mine_unstable(old, new)
    write_candidates_csv(rows, args.out)
    print(f"wrote {len(rows)} candidates to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
