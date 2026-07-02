import math

from cap_mosaic.core.palette import lab_to_rgb, rgb_to_lab
from cap_mosaic.vision.card_reader import neutralize_cast


def _chroma(rgb):
    _, a, b = rgb_to_lab(rgb)
    return math.hypot(a, b)


def _ab(rgb):
    _, a, b = rgb_to_lab(rgb)
    return (a, b)


def test_lab_rgb_roundtrips():
    for rgb in [(0, 0, 0), (255, 255, 255), (162, 148, 129), (29, 162, 193),
                (190, 40, 45), (128, 128, 128)]:
        back = lab_to_rgb(rgb_to_lab(rgb))
        assert all(abs(a - b) <= 2 for a, b in zip(rgb, back)), (rgb, back)


def test_metal_warmth_from_the_lamp_is_removed():
    # a silver cap mirrors the warm lamp; the gray strip shows that same cast, so
    # subtracting the strip's cast neutralises the silver
    silver = (162, 148, 129)
    assert _chroma(silver) > 12  # reads warm/tan
    fixed = neutralize_cast(silver, _ab(silver))  # cast measured off the strip
    assert _chroma(fixed) < 3  # now true gray
    assert abs(fixed[0] - fixed[2]) < 6  # R ~ B, no warm bias


def test_partial_cast_reduces_but_does_not_overshoot():
    silver = (162, 148, 129)
    a, b = _ab(silver)
    fixed = neutralize_cast(silver, (a * 0.5, b * 0.5))  # strip cast is smaller
    assert 3 < _chroma(fixed) < _chroma(silver)  # warmth reduced, not zeroed


def test_saturated_colour_survives_a_small_cast():
    blue = (29, 162, 193)
    fixed = neutralize_cast(blue, (2.0, 6.0))  # small warm cast removed
    # a genuinely colourful cap stays colourful (not desaturated to gray)
    assert _chroma(fixed) > 25
    assert fixed[2] > fixed[0]  # still blue-dominant


def test_genuine_tan_under_neutral_light_is_kept():
    # neutral light -> zero cast -> a real tan/cream cap must NOT be greyed out
    tan = (198, 176, 140)
    fixed = neutralize_cast(tan, (0.0, 0.0))
    assert _chroma(fixed) > 10  # still clearly tan, not neutralised
