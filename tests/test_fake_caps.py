import numpy as np

from cap_mosaic.app import fake_caps
from cap_mosaic.core.palette import ciede2000, rgb_to_lab


def _circle_median(img_rgba):
    a = np.asarray(img_rgba)
    rgb, alpha = a[..., :3], a[..., 3]
    inside = alpha > 128
    return np.median(rgb[inside], axis=0)


def test_library_generates_one_cap_per_colour():
    colors = [(200, 30, 30), (30, 80, 160), (230, 200, 70)]
    lib = fake_caps.fake_cap_library(colors, size=48, seed=1)
    assert len(lib) == 3
    for cap in lib:
        assert cap.image.size == (48, 48)
        assert cap.image.mode == "RGBA"


def test_cap_dominant_colour_matches_request():
    lib = fake_caps.fake_cap_library([(40, 90, 170)], size=64, seed=2)
    med = _circle_median(lib[0].image)
    de = ciede2000(rgb_to_lab(tuple(int(v) for v in med)), rgb_to_lab((40, 90, 170)))
    assert de < 25, (med, de)


def test_caps_have_markings_not_flat():
    # a real cap has rim + logo -> non-zero variance inside the disc
    cap = fake_caps.fake_cap_library([(200, 200, 200)], size=64, seed=3)[0]
    a = np.asarray(cap.image)
    inside = a[..., 3] > 128
    gray = a[..., :3].mean(axis=2)[inside]
    assert gray.std() > 5.0


def test_seed_is_deterministic():
    a = fake_caps.fake_cap_library([(120, 60, 40)], size=48, seed=7)[0]
    b = fake_caps.fake_cap_library([(120, 60, 40)], size=48, seed=7)[0]
    assert np.array_equal(np.asarray(a.image), np.asarray(b.image))
