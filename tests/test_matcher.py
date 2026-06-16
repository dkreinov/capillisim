from PIL import Image

from cap_mosaic.app import planner_designer as designer
from cap_mosaic.core.geometry import Cap, grid_for_caps_across
from cap_mosaic.core.matcher import Matcher


def _green_plan():
    grid = grid_for_caps_across(6, aspect_ratio=1.0, cap=Cap(32.0))
    img = Image.new("RGB", (96, 96), (40, 120, 70))  # all green
    return designer.plan_from_image(img, grid)


def test_matches_close_color_and_accepts():
    plan = _green_plan()
    m = Matcher(plan).match((45, 122, 72))
    assert m.accepted
    assert m.cell is not None and m.cell.color_name == "green"


def test_rejects_color_with_no_close_cell():
    plan = _green_plan()  # only green cells
    m = Matcher(plan).match((200, 30, 30))  # red cap, nothing close
    assert not m.accepted


def test_placement_consumes_a_cell():
    plan = _green_plan()
    matcher = Matcher(plan)
    before = plan.filled_count
    m = matcher.match((40, 120, 70))
    matcher.place(m.cell)
    assert plan.filled_count == before + 1
    # the same cell is not offered again
    m2 = matcher.match((40, 120, 70))
    assert m2.cell is not m.cell


def test_rejects_when_board_full():
    plan = _green_plan()
    for c in plan.cells:
        c.filled = True
    m = Matcher(plan).match((40, 120, 70))
    assert m.cell is None and not m.accepted


def test_tie_break_fills_top_left_first():
    plan = _green_plan()
    m = Matcher(plan).match((40, 120, 70))
    assert (m.cell.row, m.cell.col) == (0, 0)
