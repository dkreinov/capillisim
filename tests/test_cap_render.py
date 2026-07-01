import numpy as np

from cap_mosaic.app import cap_render
from cap_mosaic.app.planner_designer import demo_image, plan_from_image, simulate_distance
from cap_mosaic.core.geometry import Cap, grid_for_caps_across


def _hf_energy(img):
    a = np.asarray(img.convert("L"), float)
    lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return lap.var()


def _plan():
    img = demo_image(128)
    grid = grid_for_caps_across(8, aspect_ratio=1.0, cap=Cap())
    return plan_from_image(img, grid)


def test_build_library_makes_variants_per_colour():
    colors = [(200, 30, 30), (30, 80, 160), (230, 200, 70)]
    lib = cap_render.build_library(colors, db_path=None, size=48, variants=3)
    assert len(lib) == 9  # 3 colours x 3 variants for a diverse mosaic
    # variants of a colour differ (shade jitter / different logos)
    reds = [c for c in lib if abs(c.rgb[0] - 200) < 40 and c.rgb[1] < 90]
    assert len({c.rgb for c in reds}) >= 2


def test_render_produces_sized_canvas():
    plan = _plan()
    colors = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    lib = cap_render.build_library(colors, size=48)
    mosaic = cap_render.render_mosaic_caps(plan, lib, px_per_cap=24)
    assert mosaic.size[0] > 0 and mosaic.size[1] > 0
    assert mosaic.mode == "RGB"


def test_close_up_has_cap_texture_that_distance_blurs_away():
    plan = _plan()
    colors = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    lib = cap_render.build_library(colors, size=48)
    mosaic = cap_render.render_mosaic_caps(plan, lib, px_per_cap=24)
    blurred = simulate_distance(mosaic, px_per_mm=24 / 32.0, distance_m=12.0)
    # up close the caps (rims/markings) create high-frequency detail; distance blurs it
    assert _hf_energy(mosaic) > _hf_energy(blurred)
