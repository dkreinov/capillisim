import numpy as np

from cap_mosaic.core import estimator


def _solid(size=200):
    return np.full((size, size, 3), 128, np.uint8)


def _fine_checker(size=200, cell=4):
    yy, xx = np.mgrid[0:size, 0:size]
    c = (((xx // cell) + (yy // cell)) % 2 * 255).astype(np.uint8)
    return np.stack([c, c, c], axis=-1)


def test_valid_size_is_legible_no_warning():
    r = estimator.solve_from_size(_solid(), width_mm=2000)
    assert r["legible"] is True
    assert r["warning"] is None
    assert r["caps_across"] >= r["min_caps_across"]
    assert r["total_caps"] > 0


def test_too_small_size_warns_cannot_represent():
    r = estimator.solve_from_size(_fine_checker(), width_mm=250)  # ~7 caps across
    assert r["legible"] is False
    assert r["warning"] and "Too few caps" in r["warning"]
    # a large enough size is always representable
    big = estimator.solve_from_size(_fine_checker(), width_mm=6000)
    assert big["legible"] is True and big["warning"] is None


def test_distance_gives_size_and_read_quality():
    near = estimator.solve_from_distance(_solid(), distance_m=1.0)
    far = estimator.solve_from_distance(_solid(), distance_m=8.0)
    # farther viewing -> bigger recommended piece -> more caps across
    assert far["caps_across"] > near["caps_across"]
    # up close individual caps are visible; far it reads as a picture
    assert near["read_quality"] == "caps"
    assert far["read_quality"] in ("reads", "smooth")


def test_close_distance_warns_caps_visible():
    r = estimator.solve_from_distance(_solid(), distance_m=1.0)
    assert r["warning"] and "caps are visible" in r["warning"]


def test_effective_colors_shrink_with_distance():
    palette = [
        (200, 30, 30), (210, 60, 40), (30, 160, 70),
        (40, 80, 160), (60, 100, 180), (230, 200, 70),
        (240, 240, 240), (20, 20, 20),
    ]
    near = estimator.effective_colors(palette, distance_m=0.8)
    far = estimator.effective_colors(palette, distance_m=40.0)
    assert len(far) < len(near)
    assert len(near) <= len(palette)
