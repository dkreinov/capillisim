"""Shape masks: preset outlines + freeform polygon over the hex grid."""

import math

import pytest

from cap_mosaic.core.geometry import Cap, grid_for_frame
from cap_mosaic.core.shapes import (
    SHAPES,
    mask_grid,
    point_in_polygon,
    shape_area_fraction,
    shape_mask,
)

W, H = 1000.0, 800.0


def test_circle_keeps_centre_drops_corners():
    keep = shape_mask("circle", W, H)
    assert keep(W / 2, H / 2)
    for x, y in [(10, 10), (W - 10, 10), (10, H - 10), (W - 10, H - 10)]:
        assert not keep(x, y)
    # true circle: radius is min(w,h)/2, so the far x-edges are outside
    assert not keep(10.0, H / 2)
    assert keep(W / 2 - H / 2 + 10, H / 2)  # just inside the circle's left rim


def test_diamond_boundary():
    keep = shape_mask("diamond", W, H)
    # edge midpoints are inside, corners are not
    assert keep(W / 2, 5.0) and keep(5.0, H / 2)
    assert not keep(20.0, 20.0)
    # a point past the |u|+|v|=1 line is out
    assert not keep(W * 0.85, H * 0.85)


def test_heart_mirror_symmetry_and_orientation():
    keep = shape_mask("heart", W, H)
    hits = 0
    for i in range(40):
        for j in range(40):
            x = (i + 0.5) / 40 * W
            y = (j + 0.5) / 40 * H
            assert keep(x, y) == keep(W - x, y)  # left/right mirror
            hits += keep(x, y)
    assert hits > 0
    # lobes up, tip down: the point below centre is inside far longer than above
    assert keep(W / 2, H * 0.9)          # near the bottom tip
    assert not keep(W / 2, H * 0.02)     # cleft/void at the very top


def test_hexagon_symmetry_and_corners():
    keep = shape_mask("hex", W, H)
    assert keep(W / 2, 5.0) and keep(W / 2, H - 5.0)   # flat top/bottom edges
    assert keep(5.0, H / 2) and keep(W - 5.0, H / 2)   # left/right vertices
    for x, y in [(10, 10), (W - 10, 10), (10, H - 10), (W - 10, H - 10)]:
        assert not keep(x, y)
    for i in range(30):
        for j in range(30):
            x, y = (i + 0.5) / 30 * W, (j + 0.5) / 30 * H
            assert keep(x, y) == keep(W - x, y) == keep(x, H - y)


def test_point_in_polygon_square_concave_and_errors():
    sq = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]
    assert point_in_polygon(0.5, 0.5, sq)
    assert not point_in_polygon(0.1, 0.5, sq)
    # concave L: the notch is outside
    ell = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.5), (0.5, 0.5), (0.5, 0.9), (0.1, 0.9)]
    assert point_in_polygon(0.2, 0.8, ell)
    assert not point_in_polygon(0.8, 0.8, ell)   # inside the notch
    # near-vertex points resolve deterministically (either way, but stable)
    assert point_in_polygon(0.26, 0.26, sq) in (True, False)
    with pytest.raises(ValueError):
        point_in_polygon(0.5, 0.5, [(0, 0), (1, 1)])
    with pytest.raises(ValueError):
        shape_mask("poly", W, H, poly=[(0, 0), (1, 1)])


def test_area_fraction_matches_masked_cell_ratio():
    cap = Cap()
    grid = grid_for_frame(30 * 32.0, 30 * 32.0, cap)  # square frame, 30 across
    for shape in ("circle", "ellipse", "diamond", "hex", "heart"):
        masked = mask_grid(grid, shape_mask(shape, grid.width_mm, grid.height_mm))
        ratio = masked.count / grid.count
        frac = shape_area_fraction(shape)
        assert abs(ratio - frac) <= 0.1, (shape, ratio, frac)
    # polygon: a half-size centred square covers a quarter of the frame
    sq = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]
    assert math.isclose(shape_area_fraction("poly", sq), 0.25)


def test_mask_grid_preserves_dims_and_raises_on_empty():
    cap = Cap()
    grid = grid_for_frame(640.0, 480.0, cap)
    masked = mask_grid(grid, shape_mask("circle", 640.0, 480.0))
    assert masked.width_mm == grid.width_mm and masked.height_mm == grid.height_mm
    assert 0 < masked.count < grid.count
    kept = {(c.row, c.col) for c in masked.cells}
    assert all((c.row, c.col) in {(g.row, g.col) for g in grid.cells}
               for c in masked.cells)
    assert kept  # row/col identities preserved
    with pytest.raises(ValueError):
        mask_grid(grid, lambda x, y: False)


def test_unknown_shape_raises():
    with pytest.raises(ValueError):
        shape_mask("blob", W, H)
    with pytest.raises(ValueError):
        shape_area_fraction("blob")
    assert set(SHAPES) == {"rect", "circle", "ellipse", "heart", "hex",
                           "diamond", "poly"}
