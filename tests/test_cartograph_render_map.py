"""Tests for cartograph SVG/grid map rendering."""

import json
from pathlib import Path

import numpy as np
import pytest

from ks.cartograph.mosaic import MosaicResult
from ks.cartograph.render_map import (
    MapEntity,
    render_excel_grid_csv,
    render_digital_map_json,
    render_iso_overlay_unrotated,
    render_isometric_svg,
    write_map_bundle,
)


def _diamond_mosaic(
    tmp_path: Path,
    image: np.ndarray | None = None,
    *,
    affine: bool = True,
    matrix: tuple[tuple[float, float], tuple[float, float]] = (
        (2.0, -2.0),
        (1.0, 1.0),
    ),
) -> MosaicResult:
    if image is None:
        image = np.zeros((9, 9, 3), dtype=np.uint8)
    fields = dict(
        image=image,
        path=tmp_path / "source-panorama.png",
        center=(10, 20),
        scale_x=10.0,
        scale_y=20.0,
        origin_x=4.0,
        origin_y=4.0,
        band_w=9,
        band_h=9,
    )
    if affine:
        fields["world_to_pixel_matrix"] = matrix
    return MosaicResult(**fields)


def test_isometric_contains_vector_icons_not_images():
    ents = [
        MapEntity("city", 100, 200, "My City", level=6, w=2, h=2),
        MapEntity("beast", 105, 198, "Beast", level=9),
        MapEntity("wood", 102, 201, "Wood", level=3),
    ]
    svg = render_isometric_svg(ents, center=(103, 200), kingdom="2379")
    assert "icon-city" in svg
    assert "icon-beast" in svg
    assert "icon-wood" in svg
    assert "<image" not in svg
    assert "My City" in svg


def test_excel_grid_has_headers_and_cells(tmp_path):
    ents = [MapEntity("city", 10, 20, "A", level=6, w=2, h=2)]
    csv_text = render_excel_grid_csv(ents, center=(11, 21), pad_tiles=1)
    assert "Y\\X" in csv_text
    assert "CITL6:A" in csv_text or "city" in csv_text.lower() or "CIT" in csv_text
    html, grid, ent = write_map_bundle(tmp_path, ents, center=(11, 21), kingdom="1")
    assert html.is_file() and grid.is_file() and ent.is_file()


def test_affine_panorama_overlay_centers_grid_tile_at_world_coordinate(
    tmp_path: Path,
):
    mosaic = _diamond_mosaic(tmp_path)

    overlay = render_iso_overlay_unrotated(
        [],
        mosaic=mosaic,
    )

    assert "points='4.0,3.0 6.0,4.0 4.0,5.0 2.0,4.0'" in overlay


def test_affine_panorama_overlay_projects_entity_footprint_from_center_anchor(
    tmp_path: Path,
):
    mosaic = _diamond_mosaic(tmp_path)

    overlay = render_iso_overlay_unrotated(
        [MapEntity("city", 10, 20, "A", w=2, h=3)],
        mosaic=mosaic,
    )

    assert "points='4.0,3.0 8.0,5.0 2.0,8.0 -2.0,6.0'" in overlay


def test_legacy_panorama_overlay_preserves_exact_pre_task_3_geometry(
    tmp_path: Path,
):
    mosaic = _diamond_mosaic(tmp_path, affine=False)

    overlay = render_iso_overlay_unrotated(
        [MapEntity("city", 10, 20, "Legacy City", w=2, h=3)],
        mosaic=mosaic,
    )

    assert "points='4.0,4.0 9.8,14.0 4.0,24.0 -1.8,14.0'" in overlay
    assert "points='4.0,4.0 15.5,24.0 -1.8,54.0 -13.2,34.0'" in overlay
    assert '<use href="#uicon-city" x="-2.0" y="35.0"/>' in overlay
    assert "<text x='14.0' y='73.0' text-anchor='middle'>Legacy City</text>" in overlay
    assert "y='87.0'" not in overlay
    assert "fill='#cfe8d4'" not in overlay


def test_sparse_overlay_uses_lattice_step_and_filters_non_pin_kinds(
    tmp_path: Path,
):
    mosaic = _diamond_mosaic(tmp_path)
    overlay = render_iso_overlay_unrotated(
        [
            MapEntity("city", 10, 20, "Capital", w=2, h=2),
            MapEntity("rss", 12, 20, "Farm", level=3),
        ],
        mosaic=mosaic,
        lattice_step=2,
    )

    assert "sparse diamond grid (step 2)" in overlay
    assert "Capital" in overlay
    assert "Farm" not in overlay
    # Neighbor tile one step off the lattice should not be drawn.
    assert "points='6.0,4.0 8.0,5.0 6.0,6.0 4.0,5.0'" not in overlay


def test_digital_map_json_exports_covered_tiles_projection_and_entities(
    tmp_path: Path,
):
    image = np.zeros((9, 9, 3), dtype=np.uint8)
    image[4, 4] = (10, 20, 30)
    image[5, 6] = (40, 50, 60)
    mosaic = _diamond_mosaic(tmp_path, image)
    entities = [MapEntity("city", 10, 20, "Capital", level=7, w=2, h=3)]

    rendered = render_digital_map_json(
        entities,
        center=(10, 20),
        kingdom="2379",
        mosaic=mosaic,
    )
    document = json.loads(rendered)

    assert rendered == render_digital_map_json(
        entities,
        center=(10, 20),
        kingdom="2379",
        mosaic=mosaic,
    )
    assert document["kingdom"] == "2379"
    assert document["center"] == {"x": 10, "y": 20}
    assert document["projection"] == {
        "center": [10.0, 20.0],
        "pixel_origin": [4.0, 4.0],
        "matrix": [[2.0, -2.0], [1.0, 1.0]],
    }
    assert document["panorama"] == {"width": 9, "height": 9}
    assert document["entities"] == [
        {
            "kind": "city",
            "label": "Capital",
            "level": 7,
            "x": 10,
            "y": 20,
            "w": 2,
            "h": 3,
        }
    ]
    assert document["tiles"] == [
        {
            "x": 10,
            "y": 20,
            "pixel_center": [4.0, 4.0],
            "polygon": [[4.0, 3.0], [6.0, 4.0], [4.0, 5.0], [2.0, 4.0]],
            "covered": True,
            "terrain": "unknown",
            "sampled_rgb": [30, 20, 10],
        },
        {
            "x": 11,
            "y": 20,
            "pixel_center": [6.0, 5.0],
            "polygon": [[6.0, 4.0], [8.0, 5.0], [6.0, 6.0], [4.0, 5.0]],
            "covered": True,
            "terrain": "unknown",
            "sampled_rgb": [60, 50, 40],
        },
    ]


def test_digital_map_json_rejects_unbounded_tile_extent(tmp_path: Path):
    mosaic = _diamond_mosaic(
        tmp_path,
        matrix=((0.028, 0.0), (0.0, 0.028)),
    )

    with pytest.raises(
        ValueError,
        match=r"tile bounds exceed safe export limit; candidate grid is \d+x\d+",
    ):
        render_digital_map_json(
            [],
            center=(10, 20),
            kingdom="2379",
            mosaic=mosaic,
        )


def test_digital_map_json_rejects_center_different_from_mosaic(tmp_path: Path):
    mosaic = _diamond_mosaic(tmp_path)

    with pytest.raises(
        ValueError,
        match=r"center must match mosaic center; got \(11, 20\) vs \(10, 20\)",
    ):
        render_digital_map_json(
            [],
            center=(11, 20),
            kingdom="2379",
            mosaic=mosaic,
        )


def test_digital_map_json_excludes_bgra_fill_and_transparent_centers(
    tmp_path: Path,
):
    image = np.zeros((9, 9, 4), dtype=np.uint8)
    image[4, 4] = (0, 0, 0, 255)
    image[5, 2] = (70, 80, 90, 0)
    image[5, 6] = (40, 50, 60, 255)
    mosaic = _diamond_mosaic(tmp_path, image)

    document = json.loads(
        render_digital_map_json(
            [],
            center=(10, 20),
            kingdom="2379",
            mosaic=mosaic,
        )
    )

    assert [(tile["x"], tile["y"]) for tile in document["tiles"]] == [(11, 20)]
    assert document["tiles"][0]["sampled_rgb"] == [60, 50, 40]


def test_write_map_bundle_writes_and_links_canonical_json(tmp_path: Path):
    image = np.zeros((9, 9, 3), dtype=np.uint8)
    image[4, 4] = (10, 20, 30)
    mosaic = _diamond_mosaic(tmp_path, image)
    entities = [MapEntity("city", 10, 20, "Capital", level=7, w=2, h=3)]

    returned_paths = write_map_bundle(
        tmp_path,
        entities,
        center=(10, 20),
        kingdom="2379",
        mosaic=mosaic,
    )

    assert len(returned_paths) == 3
    map_json_path = tmp_path / "map.json"
    assert map_json_path.is_file()
    map_document = json.loads(map_json_path.read_text(encoding="utf-8"))
    assert map_document["tiles"]
    assert map_document["entities"] == [
        {
            "kind": "city",
            "label": "Capital",
            "level": 7,
            "x": 10,
            "y": 20,
            "w": 2,
            "h": 3,
        }
    ]
    html = returned_paths[0].read_text(encoding="utf-8")
    assert '<a href="map.json">map.json</a>' in html
    assert "position:relative;width:9px;height:9px" in html
    assert "width='9' height='9' viewBox='0 0 9 9'" in html
    assert "width:100%;height:100%;pointer-events:none" in html
    assert "points='4.0,3.0 8.0,5.0 2.0,8.0 -2.0,6.0'" in html
    assert "Capital" in returned_paths[2].read_text(encoding="utf-8")


def test_digital_map_json_includes_registration_and_entity_provenance(
    tmp_path: Path,
):
    from ks.cartograph.registration import (
        EdgeRegistrationDiagnostic,
        GlobalRegistration,
        PairTranslation,
        RegistrationGraphDiagnostics,
        RegistrationMetrics,
    )

    image = np.zeros((9, 9, 3), dtype=np.uint8)
    image[4, 4] = (10, 20, 30)
    mosaic = _diamond_mosaic(tmp_path, image)
    entity = MapEntity(
        kind="city",
        x=10,
        y=20,
        label="Capital",
        level=7,
        w=2,
        h=3,
        identity="lord1",
        confidence=0.91,
        provenance="ocr_projected",
        source_frames=("c0_center", "g_1_0"),
        coordinate_residual_px=0.4,
        popup_path="popups/c0_center-1.png",
    )
    constraint = PairTranslation(
        frame_a="c0_center",
        frame_b="g_1_0",
        delta_x=10.0,
        delta_y=0.0,
        weight=5.0,
        source="static",
        inliers=24,
    )
    registration = GlobalRegistration(
        frame_offsets={"c0_center": (0.0, 0.0), "g_1_0": (10.0, 0.0)},
        metrics=RegistrationMetrics(
            median_px=0.2,
            p95_px=0.5,
            max_px=0.8,
            connected_frames=("c0_center", "g_1_0"),
        ),
        accepted=(constraint,),
        rejected=(),
        diagnostics=(
            EdgeRegistrationDiagnostic(
                constraint=constraint,
                residual_px=0.3,
                accepted=True,
                effective_weight=5.0,
                source="static",
                inliers=24,
            ),
        ),
        graph=RegistrationGraphDiagnostics(
            connected=True,
            expected_frame_count=2,
            connected_frame_count=2,
            constraint_count=1,
            accepted_count=1,
            rejected_count=0,
        ),
    )

    document = json.loads(
        render_digital_map_json(
            [entity],
            center=(10, 20),
            kingdom="2379",
            mosaic=mosaic,
            registration=registration,
        )
    )

    assert document["registration"]["metrics"]["median_px"] == pytest.approx(0.2)
    assert document["registration"]["metrics"]["connected_frames"] == [
        "c0_center",
        "g_1_0",
    ]
    assert document["registration"]["edges"][0]["source"] == "static"
    assert document["registration"]["edges"][0]["inliers"] == 24
    assert document["entities"][0]["provenance"] == "ocr_projected"
    assert document["entities"][0]["identity"] == "lord1"
    assert document["entities"][0]["confidence"] == pytest.approx(0.91)
    assert document["entities"][0]["source_frames"] == ["c0_center", "g_1_0"]
    assert document["entities"][0]["coordinate_residual_px"] == pytest.approx(0.4)


def test_entities_csv_includes_provenance_columns():
    from ks.cartograph.render_map import render_entities_csv

    entity = MapEntity(
        kind="city",
        x=10,
        y=20,
        label="Capital",
        level=7,
        identity="lord1",
        confidence=0.91,
        provenance="popup_exact",
        source_frames=("c0_center",),
        coordinate_residual_px=0.0,
        popup_path="popups/c0.png",
    )
    csv_text = render_entities_csv([entity], center=(10, 20), kingdom="2379")
    header = csv_text.splitlines()[0]
    assert "identity" in header
    assert "confidence" in header
    assert "provenance" in header
    assert "source_frames" in header
    assert "coordinate_residual_px" in header
    assert "popup_path" in header
    assert "popup_exact" in csv_text
    assert "0.9100" in csv_text


def test_write_map_bundle_passes_registration_into_map_json(tmp_path: Path):
    from ks.cartograph.registration import (
        GlobalRegistration,
        RegistrationMetrics,
    )

    image = np.zeros((9, 9, 3), dtype=np.uint8)
    image[4, 4] = (10, 20, 30)
    mosaic = _diamond_mosaic(tmp_path, image)
    registration = GlobalRegistration(
        frame_offsets={"c0_center": (0.0, 0.0)},
        metrics=RegistrationMetrics(
            median_px=0.1,
            p95_px=0.2,
            max_px=0.3,
            connected_frames=("c0_center",),
        ),
        accepted=(),
        rejected=(),
    )
    write_map_bundle(
        tmp_path,
        [MapEntity("city", 10, 20, "Capital", level=7)],
        center=(10, 20),
        kingdom="2379",
        mosaic=mosaic,
        registration=registration,
    )
    document = json.loads((tmp_path / "map.json").read_text(encoding="utf-8"))
    assert document["registration"]["metrics"]["max_px"] == pytest.approx(0.3)
