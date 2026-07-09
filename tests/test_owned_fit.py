"""Tests for the caps-I-own fit algorithm: fit the grid to the usable cap count
and keep only owned groups within a ΔE threshold of a colour the image needs.

See plans/caps-own-fit-plan.md. Frozen contracts:
- usable_groups(groups, image, threshold_de, filter_k) -> list[Group]
- fit_caps_across(n_caps, aspect) -> int
"""

from __future__ import annotations

from PIL import Image

from cap_mosaic.app.cap_stock import Group
from cap_mosaic.app.planner_designer import (
    fit_caps_across,
    plan_from_inventory,
    usable_groups,
)
from cap_mosaic.core.geometry import Cap, grid_for_caps_across


def _labels(groups) -> set[str]:
    return {g.label for g in groups}


# --- fit_caps_across: grid cell count tracks the target cap count ---------------

def test_fit_caps_across_within_tolerance():
    """A grid built at fit_caps_across(n) totals within +/-12% of n caps.

    Realistic X (usable owned caps) is in the hundreds; test that range.
    """
    for n in (150, 300, 416):
        for aspect in (1.0, 1.5, 0.75):
            ca = fit_caps_across(n, aspect)
            assert ca >= 1
            count = grid_for_caps_across(ca, aspect, Cap()).count
            assert abs(count - n) <= 0.12 * n, (n, aspect, ca, count)


# --- usable_groups: threshold gate + monotonicity ------------------------------

def _solid(rgb, size=96):
    return Image.new("RGB", (size, size), rgb)


def test_usable_groups_threshold_crossover():
    """A group ~ΔE20 from the only image colour is excluded at thr=12 and
    included at thr=40; a near-exact group is always kept."""
    img = _solid((120, 140, 90))  # olive: the single colour the image needs
    near = Group(label="near", rgb=(123, 143, 93), count=10, cap_ids=[1])  # ΔE~1
    far = Group(label="far", rgb=(150, 120, 90), count=10, cap_ids=[2])    # ΔE~20.7
    groups = [near, far]

    at12 = _labels(usable_groups(groups, img, threshold_de=12, filter_k=16))
    at40 = _labels(usable_groups(groups, img, threshold_de=40, filter_k=16))

    assert "near" in at12 and "near" in at40      # always close enough
    assert "far" not in at12                       # rejected at the default
    assert "far" in at40                           # qualifies once relaxed


def test_usable_groups_monotone_nondecreasing():
    """|usable(thr)| is non-decreasing as the threshold grows."""
    img = _solid((120, 140, 90))
    groups = [
        Group("near", (123, 143, 93), 10, [1]),   # ΔE~1
        Group("mid", (150, 120, 90), 10, [2]),    # ΔE~20.7
        Group("far", (90, 110, 140), 10, [3]),    # ΔE~35
        Group("vfar", (70, 90, 150), 10, [4]),    # ΔE~45
    ]
    sizes = [len(usable_groups(groups, img, t, 16)) for t in (0, 5, 12, 25, 40, 60)]
    assert all(b >= a for a, b in zip(sizes, sizes[1:])), sizes
    assert sizes[0] <= 1 and sizes[-1] == 4       # grows from ~none to all


# --- end-to-end fit path: few colours, ~X cells filled -------------------------

def _rgb_blocks() -> Image.Image:
    """Three vertical colour blocks (no white) the plan must reproduce."""
    img = Image.new("RGB", (150, 100), (200, 60, 60))
    img.paste((60, 160, 80), (50, 0, 100, 100))
    img.paste((70, 90, 180), (100, 0, 150, 100))
    return img


def test_fit_path_uses_few_colours_and_fills_X_cells():
    img = _rgb_blocks()
    aspect = img.width / img.height
    groups = [
        Group("r", (205, 62, 58), 20, [1]),    # near red block
        Group("g", (58, 158, 82), 20, [2]),    # near green block
        Group("b", (72, 88, 178), 20, [3]),    # near blue block
        Group("magenta", (200, 40, 200), 20, [4]),   # far -> excluded
        Group("yellow", (230, 220, 40), 20, [5]),    # far -> excluded
        Group("black", (10, 10, 10), 20, [6]),       # far -> excluded
    ]
    usable = usable_groups(groups, img, threshold_de=12, filter_k=16)
    assert len(usable) == 3, _labels(usable)        # only the 3 image colours qualify
    X = sum(g.count for g in usable)                # usable cap count = 60

    ca = fit_caps_across(X, aspect)
    grid = grid_for_caps_across(ca, aspect, Cap())
    plan = plan_from_inventory(img, grid, usable, bare_white=False)

    filled = sum(1 for c in plan.cells if not c.is_hole)
    distinct = len({tuple(c.rgb) for c in plan.cells if not c.is_hole})

    assert distinct <= len(usable) < len(groups)    # far fewer colours than all groups
    assert filled >= 0.80 * X and filled <= X       # ~X cells filled, capped by stock
