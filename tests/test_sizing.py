import math

from cap_mosaic.core import sizing


def test_acuity_constant():
    assert sizing.ACUITY_ARCMIN == 1.5


def test_fraction_is_in_unit_interval():
    for d in (0.5, 1, 2, 5, 10, 30):
        f = sizing.apparent_fraction(1.0, d, fov_deg=50.0)
        assert 0.0 < f <= 1.0


def test_close_up_fills_the_frame():
    # A 1 m object viewed from very close subtends more than the FOV -> clamped to 1.0
    assert sizing.apparent_fraction(1.0, 0.2, fov_deg=50.0) == 1.0


def test_fraction_shrinks_monotonically_with_distance():
    fracs = [sizing.apparent_fraction(1.0, d, fov_deg=50.0) for d in (2, 4, 8, 16, 32)]
    assert all(a > b for a, b in zip(fracs, fracs[1:]))


def test_fraction_matches_angular_geometry():
    # angular width / fov, using the true half-angle formula
    width_m, distance_m, fov = 1.5, 6.0, 50.0
    ang = math.degrees(2 * math.atan((width_m / 2) / distance_m))
    assert sizing.apparent_fraction(width_m, distance_m, fov) == \
        min(1.0, ang / fov)
