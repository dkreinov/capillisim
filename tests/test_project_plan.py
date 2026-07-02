import numpy as np
from PIL import Image

from cap_mosaic.app import planner_designer as designer
from cap_mosaic.app.project_plan import ProjectSession, run_projection
from cap_mosaic.core.geometry import Cap, grid_for_caps_across
from cap_mosaic.core.palette import CapColor
from cap_mosaic.procam.calibrate import Calibration

RED, GREEN, BLUE = (200, 30, 30), (30, 170, 60), (40, 70, 190)


def _session():
    img = Image.new("RGB", (240, 240))
    for i, col in enumerate((RED, GREEN, BLUE)):
        for x in range(i * 80, i * 80 + 80):
            for y in range(240):
                img.putpixel((x, y), col)
    grid = grid_for_caps_across(12, aspect_ratio=1.0, cap=Cap())
    pal = tuple(CapColor(str(c), c) for c in (RED, GREEN, BLUE))
    plan = designer.plan_from_image(img, grid, palette=pal)
    cal = Calibration.fit_to_frame(plan.width_mm, plan.height_mm, 400, 400)
    return ProjectSession(plan, cal)


def _lit(img):
    return (np.asarray(img).sum(2) > 30).sum()


def test_loop_switches_mode_and_colour_then_quits():
    session = _session()
    frames = []
    keys = iter(["c", "n", "n", "q"])  # colour mode, next, next, quit
    run_projection(session, frames.append, lambda: next(keys, None))

    # initial full stencil + one redraw per handled key (c, n, n); 'q' doesn't redraw
    assert len(frames) == 4
    assert session.mode == "colour"
    assert session.ci == 2                       # advanced by the two 'n's
    assert _lit(frames[1]) < _lit(frames[0])     # a single colour lights fewer discs


def test_unknown_key_does_not_redraw_and_none_quits():
    session = _session()
    frames = []
    keys = iter(["x", None])  # unknown key (no redraw), then quit
    run_projection(session, frames.append, lambda: next(keys, None))
    assert len(frames) == 1  # only the initial frame


def test_stencil_and_colour_frames_are_full_projector_size():
    session = _session()
    f = session.frame()
    assert f.size == (400, 400)
