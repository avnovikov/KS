"""Tests for cartograph SVG/grid map rendering."""

from ks.cartograph.render_map import (
    MapEntity,
    render_excel_grid_csv,
    render_isometric_svg,
    write_map_bundle,
)


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
