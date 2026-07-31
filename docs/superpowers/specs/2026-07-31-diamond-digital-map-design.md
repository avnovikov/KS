# Diamond Digital Map Design

## Goal

Represent the captured KingShot world with its real diamond geometry. The
panorama, tile grid, entities, and exported digital data must all use one
world-to-pixel affine projection.

## Coordinate model

World coordinates are integer tile coordinates `(x, y)`. Their pixel position
is:

`pixel = panorama_origin + world_to_pixel @ (world - world_center)`

The two columns of `world_to_pixel` are the diagonal screen vectors for one
world-X tile and one world-Y tile. They must not be reduced to independent
horizontal and vertical scales.

The projection is invertible. Panorama bounds are calculated by inverse
projecting all four image corners, not by dividing image width and height by
axis-aligned scales.

## Mosaic

`MosaicResult` retains legacy scalar scales for compatibility and additionally
stores the full 2×2 world-to-pixel matrix. All new coordinate conversion uses
the matrix when present.

The existing 25-frame capture is reconstructed from the exact per-frame
viewport coordinates and the affine matrix calibrated from clicked Badland
coordinates. Popup screenshots are observations only; clean screenshots remain
the visual source.

## Digital representation

`map.json` is the canonical machine-readable export. It contains:

- kingdom and world center;
- the affine projection and panorama dimensions;
- every integer diamond tile whose center is covered by the panorama;
- each tile's world coordinate, pixel center, four-pixel polygon, coverage
  state, and sampled center color;
- all detected static entities with kind, label, level, world coordinate, and
  footprint.

Unknown terrain is explicit (`"terrain": "unknown"`); the exporter must not
invent semantic terrain classes from color alone.

## HTML map

`map.html` shows the panorama and a correctly aligned diamond SVG overlay in
the same pixel coordinate system. Entity footprints use projected world
corners. The separate schematic and CSV views remain available for inspection.

## Error handling

- Reject non-finite, singular, or incorrectly shaped affine matrices.
- Reject invalid panorama dimensions.
- Skip tiles whose centers fall outside the image.
- Preserve existing axis-aligned behavior when loading legacy mosaics without
  a matrix.

## Verification

- Projection round trips recover world coordinates.
- Diamond corners follow both affine basis vectors.
- Inverse-projected panorama bounds include all four image corners.
- `map.json` contains projection, tiles, entities, and only covered tile
  centers.
- Existing cartograph projection, mosaic, and rendering tests remain green.
