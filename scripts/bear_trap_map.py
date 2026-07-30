#!/usr/bin/env python3
"""Run bear-trap placement sweep and write visual map + seat CSV."""

from __future__ import annotations

import csv
from pathlib import Path

import yaml

from ks.placement.geometry import Rect
from ks.placement.render import write_map
from ks.placement.sweep import Blocker, sweep

ROOT = Path(__file__).resolve().parents[1]


def load_blockers(path: Path) -> list[Blocker]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    blocks = []
    for item in raw.get("blocks", []):
        blocks.append(
            Blocker(
                id=str(item["id"]),
                kind=str(item.get("kind", "blocked")),
                rect=Rect(int(item["x"]), int(item["y"]), int(item["w"]), int(item["h"])),
            )
        )
    return blocks


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config" / "bear_trap.yaml").read_text(encoding="utf-8"))
    blockers = load_blockers(ROOT / "assets" / "reference" / "bear-trap" / "blockers.yaml")
    trap2 = (int(cfg["trap2"]["x"]), int(cfg["trap2"]["y"]))

    ranked = sweep(
        trap2,
        blockers,
        d_min=int(cfg["d_min"]),
        d_max=int(cfg["d_max"]),
        directions=list(cfg["directions"]),
        lateral_offsets=list(cfg["lateral_offsets"]),
        preferred_d=int(cfg.get("preferred_d", 7)),
        preferred_directions=list(cfg.get("preferred_directions", ["E", "W"])),
        city_size=int(cfg["city_size"]),
        trap_size=int(cfg["trap_size"]),
        radius_leader=float(cfg["radius_leader_tiles"]),
        radius_joiner_cycle=float(cfg["radius_joiner_cycle_tiles"]),
        leaders_per_trap=int(cfg["leaders_per_trap"]),
        min_leaders=int(cfg["min_leaders_per_trap"]),
        weights=dict(cfg["weights"]),
    )
    assert ranked, "sweep returned no feasible layouts — check blockers / D range"
    best = ranked[0]

    out_html = ROOT / "assets" / "reference" / "bear-trap" / "placement-map.html"
    out_csv = ROOT / "assets" / "reference" / "bear-trap" / "seats.csv"
    write_map(out_html, best, ranked)

    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["seat_x", "seat_y", "role", "assigned_leader_x", "assigned_leader_y", "t_l", "t_j"])
        for s in sorted(best.seats, key=lambda s: (s.y, s.x)):
            lx, ly = s.assigned_leader if s.assigned_leader else ("", "")
            w.writerow([s.x, s.y, s.role, lx, ly, s.t_l, s.t_j])

    print(f"best D={best.d} {best.direction} lateral={best.lateral} score={best.score:.1f}")
    print(f"  trap2={best.trap2} new_trap={best.trap1}")
    print(f"  L2={best.n_l2} L1={best.n_l1} flex={best.n_flex} join_ok={best.n_join_ok}")
    print(f"wrote {out_html}")
    print(f"wrote {out_csv}")
    print("top 8:")
    for i, r in enumerate(ranked[:8], 1):
        print(
            f"  {i}. D={r.d} {r.direction} lat={r.lateral} "
            f"score={r.score:.1f} L2={r.n_l2} L1={r.n_l1} "
            f"flex={r.n_flex} join={r.n_join_ok} t1={r.trap1}"
        )


if __name__ == "__main__":
    main()
