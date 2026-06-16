from PIL import Image

from cap_mosaic.app import planner_designer as designer
from cap_mosaic.app.build_loop import BuildSession, run_loop
from cap_mosaic.core.geometry import Cap, grid_for_caps_across
from cap_mosaic.procam.calibrate import Calibration


def _session():
    grid = grid_for_caps_across(6, aspect_ratio=1.0, cap=Cap(32.0))
    img = Image.new("RGB", (96, 96), (40, 120, 70))  # all-green plan
    plan = designer.plan_from_image(img, grid)
    src = [(0, 0), (192, 0), (0, 192), (192, 192)]
    dst = [(4 * x, 4 * y) for x, y in src]
    cal = Calibration.from_correspondences(src, dst, 1024, 1024)
    return BuildSession(plan, cal)


def _solid(rgb):
    return Image.new("RGB", (64, 64), rgb)


def test_full_loop_places_matching_caps_and_rejects_others():
    session = _session()
    # five good green caps, then a red one (no green-free... no red cells), then stop
    frames = [_solid((40, 120, 70))] * 5 + [_solid((200, 30, 30))] + [None]
    it = iter(frames)
    shown = []
    saves = []

    stats = run_loop(
        session,
        cap_source=lambda: next(it),
        display=lambda img: shown.append(img),
        confirm=lambda match: True,
        on_save=lambda plan: saves.append(plan.filled_count),
    )

    assert stats.placed == 5
    assert stats.rejected == 1
    assert stats.skipped == 0
    assert session.plan.filled_count == 5
    assert saves == [1, 2, 3, 4, 5]  # persisted after each placement
    assert len(shown) == 6  # a projector frame per cap seen (placements + reject)


def test_skipped_caps_are_not_placed():
    session = _session()
    frames = [_solid((40, 120, 70)), _solid((40, 120, 70)), None]
    it = iter(frames)
    # user declines the first highlight, accepts the second
    answers = iter([False, True])

    stats = run_loop(
        session,
        cap_source=lambda: next(it),
        display=lambda img: None,
        confirm=lambda match: next(answers),
    )

    assert stats.placed == 1
    assert stats.skipped == 1
    assert session.plan.filled_count == 1
