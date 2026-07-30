"""Tests for cartograph pipeline helpers."""

from pathlib import Path

import numpy as np
import yaml

from ks.cartograph.labels import hits_from_label_boxes, infer_kind
from ks.cartograph.mask import MaskConfig
from ks.cartograph.pipeline import (
    dry_run_plan,
    format_dry_run,
    hits_to_blockers_yaml,
    run_fixture_dir,
)


def test_infer_kind() -> None:
    assert infer_kind("25 [UTD] ACE") == "city"
    assert infer_kind("[UTD] Hunting Trap 2") == "trap"
    assert infer_kind("[UTD] Plains HQ") == "hq"


def test_dry_run_format() -> None:
    text = format_dry_run(dry_run_plan(698, 816, 30, 10))
    assert "698,816" in text
    assert "jumps=" in text


def test_hits_to_yaml_roundtrip() -> None:
    from ks.cartograph.models import StructureHit

    hits = [StructureHit.from_kind("ACE", "city", 696, 814)]
    raw = yaml.safe_load(hits_to_blockers_yaml(hits))
    assert raw["blocks"][0]["w"] == 2


def test_fixture_pipeline_with_injected_labels(tmp_path: Path) -> None:
    import cv2

    shot = tmp_path / "b3-01.png"
    img = np.full((200, 100, 3), 80, dtype=np.uint8)
    cv2.imwrite(str(shot), img)
    cfg = MaskConfig(rects=(), crop_top=0.1, crop_bottom=0.9)
    mat = np.eye(2) * 10.0
    out = tmp_path / "out.yaml"
    result = run_fixture_dir(
        tmp_path,
        viewports={"b3-01": (697, 819)},
        mask_cfg=cfg,
        radius=30,
        mat=mat,
        out_yaml=out,
        label_boxes_by_stem={
            "b3-01": [("[UTD] Hunting Trap 2", 50.0, 80.0)],
        },
    )
    assert out.exists()
    assert result.center == (697, 819)
    assert any(h.kind == "trap" for h in result.hits)


def test_hits_from_boxes_uses_mat() -> None:
    mat = np.eye(2) * 10.0
    hits = hits_from_label_boxes(
        [("25 [UTD] ACE", 50.0, 40.0)],
        viewport=(700.0, 820.0),
        crop_center=(50.0, 40.0),
        mat=mat,
        source="t",
    )
    assert len(hits) == 1
    assert hits[0].x == 700 and hits[0].y == 820
