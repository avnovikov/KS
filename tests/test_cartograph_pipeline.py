"""Tests for cartograph pipeline helpers."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from ks.cartograph.labels import hits_from_label_boxes, infer_kind
from ks.cartograph.mask import MaskConfig
from ks.cartograph.pipeline import (
    dry_run_plan,
    find_seed_calibration_path,
    format_dry_run,
    hits_to_blockers_yaml,
    resolve_capture_stitch_route,
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


def test_find_seed_and_stitch_route_prefers_exact_click(tmp_path: Path) -> None:
    assert find_seed_calibration_path(tmp_path) is None
    route = resolve_capture_stitch_route(tmp_path)
    assert route.mode == "viewport_fallback"
    assert route.seed_path is None
    assert "weak" in route.detail.lower() or "fallback" in route.detail.lower()

    other = tmp_path / "exact-coordinate-calibration-v1.yaml"
    other.write_text("matrix: [[1,0],[0,1]]\nframe_offsets: {}\n", encoding="utf-8")
    preferred = tmp_path / "exact-coordinate-calibration-v3.yaml"
    preferred.write_text("matrix: [[1,0],[0,1]]\nframe_offsets: {}\n", encoding="utf-8")
    assert find_seed_calibration_path(tmp_path) == preferred
    route2 = resolve_capture_stitch_route(tmp_path)
    assert route2.mode == "register"
    assert route2.seed_path == preferred


def test_cli_map_require_registration_fails_without_seed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ks.cartograph.cli import main

    code = main(
        ["--map", "--require-registration", "--capture-dir", str(tmp_path)]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "exact-click" in err.lower() or "seed" in err.lower()


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


def _write_synthetic_grid_capture(capture_dir: Path) -> Path:
    import cv2

    capture_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    frames = {
        "c0_center": (1116, 287),
        "g_1_0": (1118, 287),
        "g_0_1": (1116, 289),
    }
    for name, viewport in frames.items():
        image = np.zeros((1920, 1080, 3), dtype=np.uint8)
        image[:] = (40, 110, 50)
        noise = rng.integers(0, 40, size=(400, 400, 3), dtype=np.uint8)
        image[700:1100, 340:740] = noise
        cv2.imwrite(str(capture_dir / f"{name}.png"), image)
        _ = viewport

    seed = {
        "reference_frame": "c0_center",
        "matrix": [[100.0, -100.0], [-80.0, -80.0]],
        "frame_offsets": {
            "c0_center": [0.0, 0.0],
            "g_1_0": [120.0, 0.0],
            "g_0_1": [0.0, 140.0],
        },
        "observations": {
            "c0_center": {"world": [1116, 287], "selected_pixel": [540.0, 960.0]},
        },
    }
    seed_path = capture_dir / "exact-coordinate-calibration-v3.yaml"
    seed_path.write_text(yaml.safe_dump(seed), encoding="utf-8")
    (capture_dir / "calibration.yaml").write_text(
        yaml.safe_dump(
            {
                "viewports": {
                    name: list(viewport) for name, viewport in frames.items()
                }
            }
        ),
        encoding="utf-8",
    )
    return seed_path


def test_register_and_digitize_capture_exports_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from ks.cartograph import pipeline as pipeline_module
    from ks.cartograph.entities import EntityCatalogEntry
    from ks.cartograph.registration import (
        EdgeRegistrationDiagnostic,
        GlobalRegistration,
        PairTranslation,
        RegistrationGraphDiagnostics,
        RegistrationMetrics,
    )

    capture_dir = tmp_path / "capture"
    out_dir = tmp_path / "out"
    _write_synthetic_grid_capture(capture_dir)

    constraint = PairTranslation(
        frame_a="c0_center",
        frame_b="g_1_0",
        delta_x=120.0,
        delta_y=0.0,
        weight=8.0,
        source="static",
        inliers=22,
    )
    fake_registration = GlobalRegistration(
        frame_offsets={
            "c0_center": (0.0, 0.0),
            "g_1_0": (120.0, 0.0),
            "g_0_1": (0.0, 140.0),
        },
        metrics=RegistrationMetrics(
            median_px=0.4,
            p95_px=0.9,
            max_px=1.2,
            connected_frames=("c0_center", "g_0_1", "g_1_0"),
        ),
        accepted=(constraint,),
        rejected=(),
        diagnostics=(
            EdgeRegistrationDiagnostic(
                constraint=constraint,
                residual_px=0.4,
                accepted=True,
                effective_weight=8.0,
                source="static",
                inliers=22,
            ),
        ),
        graph=RegistrationGraphDiagnostics(
            connected=True,
            expected_frame_count=3,
            connected_frame_count=3,
            constraint_count=1,
            accepted_count=1,
            rejected_count=0,
        ),
    )
    catalog_entry = EntityCatalogEntry(
        identity="lord1",
        label="8 [ROY]lord1",
        kind="city",
        level=8,
        world_x=1116.1,
        world_y=287.2,
        tile_x=1116,
        tile_y=287,
        confidence=0.88,
        provenance="ocr_projected",
        source_frames=("c0_center", "g_1_0"),
        coordinate_residual_px=0.5,
        popup_path=None,
        w=2,
        h=2,
    )

    stitch_kwargs: dict = {}

    def fake_constraints(*args, **kwargs):
        return (constraint,)

    def fake_solve(*args, **kwargs):
        return fake_registration

    def fake_stitch(frames, out_path, **kwargs):
        stitch_kwargs.update(kwargs)
        import cv2
        from ks.cartograph.mosaic import MosaicResult

        image = np.zeros((40, 40, 3), dtype=np.uint8)
        image[20, 20] = (30, 40, 50)
        cv2.imwrite(str(out_path), image)
        return MosaicResult(
            image=image,
            path=out_path,
            center=(1116, 287),
            scale_x=100.0,
            scale_y=100.0,
            origin_x=20.0,
            origin_y=20.0,
            band_w=756,
            band_h=1075,
            world_to_pixel_matrix=((100.0, -100.0), (-80.0, -80.0)),
        )

    def fake_detect(*args, **kwargs):
        from ks.cartograph.entities import EntityObservation

        return [
            EntityObservation(
                frame=kwargs.get("frame", "c0_center"),
                pixel_x=10.0,
                pixel_y=10.0,
                identity="lord1",
                label="8 [ROY]lord1",
                kind="city",
                level=8,
                confidence=0.88,
                provenance="ocr_projected",
            )
        ]

    def fake_merge(*args, **kwargs):
        return [catalog_entry]

    monkeypatch.setattr(
        pipeline_module, "build_registration_constraints", fake_constraints
    )
    monkeypatch.setattr(pipeline_module, "solve_frame_translations", fake_solve)
    monkeypatch.setattr(pipeline_module, "stitch_grid_lattice", fake_stitch)
    monkeypatch.setattr(pipeline_module, "detect_frame_observations", fake_detect)
    monkeypatch.setattr(pipeline_module, "merge_entity_observations", fake_merge)
    monkeypatch.setattr(
        pipeline_module,
        "extract_name_landmarks",
        lambda band: [],
    )
    monkeypatch.setattr(
        pipeline_module,
        "competing_feature_track_pairs",
        lambda *args, **kwargs: (),
    )

    result = pipeline_module.register_and_digitize_capture(
        capture_dir,
        out_dir=out_dir,
        kingdom="2379",
    )

    assert "calibration" not in stitch_kwargs
    assert stitch_kwargs["frame_offsets"] == fake_registration.frame_offsets
    assert stitch_kwargs["world_to_pixel_matrix"] == ((100.0, -100.0), (-80.0, -80.0))
    assert (out_dir / "map.json").is_file()
    assert (out_dir / "entities.csv").is_file()
    assert (out_dir / "entities.yaml").is_file()
    assert (out_dir / "registration.yaml").is_file()
    assert (out_dir / "cartograph.sqlite").is_file()
    document = json.loads((out_dir / "map.json").read_text(encoding="utf-8"))
    assert document["registration"]["metrics"]["connected_frames"] == [
        "c0_center",
        "g_0_1",
        "g_1_0",
    ]
    assert document["entities"][0]["provenance"] == "ocr_projected"
    entities_yaml = yaml.safe_load((out_dir / "entities.yaml").read_text())
    assert entities_yaml["entities"][0]["provenance"] == "ocr_projected"
    assert entities_yaml["entities"][0]["confidence"] == pytest.approx(0.88)
    registration_yaml = yaml.safe_load((out_dir / "registration.yaml").read_text())
    assert registration_yaml["metrics"]["median_px"] == pytest.approx(0.4)
    assert registration_yaml["matrix"] == [
        [100.0, -100.0],
        [-80.0, -80.0],
    ]
    assert result.registration is fake_registration
    assert len(result.entities) == 1


def test_register_and_digitize_capture_fails_closed_on_competing_tracks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ks.cartograph import pipeline as pipeline_module
    from ks.cartograph.registration import (
        CompetingFeatureTrackError,
        GlobalRegistration,
        PairTranslation,
        RegistrationGraphDiagnostics,
        RegistrationMetrics,
    )

    capture_dir = tmp_path / "capture"
    out_dir = tmp_path / "out"
    _write_synthetic_grid_capture(capture_dir)

    fake_registration = GlobalRegistration(
        frame_offsets={
            "c0_center": (0.0, 0.0),
            "g_1_0": (120.0, 0.0),
            "g_0_1": (0.0, 140.0),
        },
        metrics=RegistrationMetrics(
            median_px=0.1,
            p95_px=0.2,
            max_px=0.3,
            connected_frames=("c0_center", "g_0_1", "g_1_0"),
        ),
        accepted=(),
        rejected=(),
        diagnostics=(),
        graph=RegistrationGraphDiagnostics(
            connected=True,
            expected_frame_count=3,
            connected_frame_count=3,
            constraint_count=0,
            accepted_count=0,
            rejected_count=0,
        ),
    )

    monkeypatch.setattr(
        pipeline_module,
        "build_registration_constraints",
        lambda *args, **kwargs: (
            PairTranslation(
                frame_a="c0_center",
                frame_b="g_1_0",
                delta_x=120.0,
                delta_y=0.0,
                weight=1.0,
                source="prior",
                inliers=0,
            ),
        ),
    )
    monkeypatch.setattr(
        pipeline_module, "solve_frame_translations", lambda *a, **k: fake_registration
    )
    monkeypatch.setattr(
        pipeline_module,
        "extract_name_landmarks",
        lambda band: [],
    )
    monkeypatch.setattr(
        pipeline_module,
        "competing_feature_track_pairs",
        lambda *args, **kwargs: (("c0_center", "g_1_0", 12.5, 9),),
    )
    stitch_calls: list[object] = []
    monkeypatch.setattr(
        pipeline_module,
        "stitch_grid_lattice",
        lambda *args, **kwargs: stitch_calls.append((args, kwargs)),
    )

    with pytest.raises(CompetingFeatureTrackError, match=r"competing feature-track"):
        pipeline_module.register_and_digitize_capture(
            capture_dir,
            out_dir=out_dir,
            kingdom="2379",
        )

    assert stitch_calls == []
    assert not (out_dir / "map.json").exists()
    assert not (out_dir / "panorama.png").exists()
    diagnostic = yaml.safe_load(
        (out_dir / "registration-competing-tracks.yaml").read_text(encoding="utf-8")
    )
    assert diagnostic["competing_feature_track_pairs"][0]["separation_px"] == pytest.approx(
        12.5
    )
