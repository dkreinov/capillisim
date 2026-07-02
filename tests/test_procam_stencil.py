import numpy as np
from PIL import Image

from cap_mosaic.app import planner_designer as designer
from cap_mosaic.core.geometry import Cap, grid_for_caps_across
from cap_mosaic.core.palette import CapColor
from cap_mosaic.procam.calibrate import Calibration
from cap_mosaic.procam.render import render_stencil

RED, GREEN, BLUE = (200, 30, 30), (30, 170, 60), (40, 70, 190)


def _three_band_image(size=240):
    img = Image.new("RGB", (size, size))
    for i, col in enumerate((RED, GREEN, BLUE)):
        for x in range(i * size // 3, (i + 1) * size // 3):
            for y in range(size):
                img.putpixel((x, y), col)
    return img


def _plan(palette, reject=None):
    grid = grid_for_caps_across(12, aspect_ratio=1.0, cap=Cap())
    pal = tuple(CapColor(str(c), c) for c in palette)
    return designer.plan_from_image(_three_band_image(), grid, palette=pal,
                                    reject_threshold=reject)


def _cal(plan):
    return Calibration.fit_to_frame(plan.width_mm, plan.height_mm, 400, 400)


def _lit(img):
    return (np.asarray(img).sum(2) > 30).sum()


def _has(img, rgb):
    a = np.asarray(img).astype(int)
    return bool(np.any(np.all(np.abs(a - np.array(rgb)) <= 12, axis=2)))


def test_full_stencil_lights_the_plan():
    plan = _plan([RED, GREEN, BLUE])
    img = render_stencil(plan, _cal(plan))
    assert _lit(img) > 0
    assert _has(img, RED) and _has(img, GREEN) and _has(img, BLUE)


def test_colour_pass_lights_only_that_colour():
    plan = _plan([RED, GREEN, BLUE])
    cal = _cal(plan)
    full = render_stencil(plan, cal)
    red_only = render_stencil(plan, cal, color=RED)
    assert _lit(red_only) < _lit(full)      # one colour lights fewer discs
    assert _has(red_only, RED)              # the chosen colour is lit
    assert not _has(red_only, BLUE)         # the others are dark


def test_holes_are_never_lit():
    # palette without green + tight reject -> the green band becomes holes
    plan = _plan([RED, BLUE], reject=10.0)
    assert plan.hole_count > 0
    cal = _cal(plan)
    img = np.asarray(render_stencil(plan, cal))
    hole = next(c for c in plan.cells if c.is_hole)
    px, py = cal.table_mm_to_proj_px(hole.x_mm, hole.y_mm)
    assert tuple(img[int(py), int(px)]) == (0, 0, 0)  # hole centre stays dark
