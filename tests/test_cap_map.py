import io

from PIL import Image

from cap_mosaic.app import planner_designer as designer
from cap_mosaic.app.cap_map import cap_map_labels, render_cap_map
from cap_mosaic.core.geometry import Cap, grid_for_caps_across


def _plan(across=10):
    img = designer.demo_image(128)
    grid = grid_for_caps_across(across, aspect_ratio=1.0, cap=Cap())
    return designer.plan_from_image(img, grid)


def test_labels_cover_every_distinct_colour():
    plan = _plan()
    labels = cap_map_labels(plan)
    distinct = {tuple(c.rgb) for c in plan.cells if not c.is_hole}
    assert set(labels) == distinct
    assert len(set(labels.values())) == len(labels)  # unique letters


def test_render_produces_rgb_image_that_scales_with_grid():
    small = render_cap_map(_plan(8))
    big = render_cap_map(_plan(20))
    assert small.mode == "RGB" and small.size[0] > 0
    assert big.size[0] > small.size[0]  # more caps across -> wider map


def test_cap_map_saves_as_pdf():
    buf = io.BytesIO()
    render_cap_map(_plan(8)).save(buf, format="PDF")
    assert buf.getvalue()[:4] == b"%PDF"
