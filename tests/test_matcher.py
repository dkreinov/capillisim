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


def _two_color_plan():
    """Plan with warm-gray cells and beige cells (distinct targets)."""
    from cap_mosaic.core.palette import CapColor

    grid = grid_for_caps_across(6, aspect_ratio=1.0, cap=Cap(32.0))
    img = Image.new("RGB", (96, 96), (149, 142, 128))  # warm gray half
    for x in range(48, 96):
        for y in range(96):
            img.putpixel((x, y), (205, 190, 160))  # beige half
    palette = (CapColor("warmgray", (149, 142, 128)), CapColor("beige", (205, 190, 160)))
    return designer.plan_from_image(img, grid, palette=palette)


def test_identify_then_place_uses_the_caps_mosaic_colour():
    from cap_mosaic.core.matcher import InventoryCap

    plan = _two_color_plan()
    # a busy cap: field reads beige-ish, but its true at-distance colour is warm gray
    inv = (InventoryCap(field=(178, 171, 153), mosaic=(149, 142, 128)),)
    matcher = Matcher(plan, inventory=inv)

    naive = matcher.match((180, 170, 152))       # raw field read -> beige cells
    smart = matcher.match_cap((180, 170, 152))   # identify -> place by mosaic
    assert naive.cell.color_name == "beige"       # the bug this fixes
    assert smart.cell.color_name == "warmgray"    # correct slot for what it looks like afar
    assert smart.accepted


def test_unknown_cap_falls_back_to_raw_colour():
    from cap_mosaic.core.matcher import InventoryCap

    plan = _two_color_plan()
    inv = (InventoryCap(field=(178, 171, 153), mosaic=(149, 142, 128)),)
    matcher = Matcher(plan, inventory=inv)
    # a red cap: nowhere near any inventory field -> use the raw read as-is
    m = matcher.match_cap((200, 30, 30))
    assert not m.accepted  # nothing red in this plan; rejected like before


def test_match_cap_without_inventory_equals_match():
    plan = _two_color_plan()
    matcher = Matcher(plan)
    a = matcher.match((206, 189, 161))
    b = matcher.match_cap((206, 189, 161))
    assert a.cell is b.cell and a.accepted == b.accepted
