import numpy as np

from cap_mosaic.core import critique


def _bold_icon(n=200):
    """A bold, high-contrast subject on a clean background (great cap art)."""
    img = np.full((n, n, 3), 240, np.uint8)          # clean light background
    yy, xx = np.mgrid[0:n, 0:n]
    disc = (xx - n / 2) ** 2 + (yy - n / 2) ** 2 < (n * 0.32) ** 2
    img[disc] = (20, 30, 180)                        # bold blue disc
    return img


def _busy_lowcontrast(n=200):
    """Low-contrast fine noise, no subject (poor cap art)."""
    rng = np.random.default_rng(0)
    return (120 + rng.integers(-18, 18, (n, n, 3))).astype(np.uint8)


def test_bold_icon_scores_higher_than_busy_noise():
    good = critique.critique(_bold_icon())
    bad = critique.critique(_busy_lowcontrast())
    assert good["score"] > bad["score"]
    assert good["score"] >= 60
    assert good["verdict"] in ("great", "good")


def test_result_shape_is_complete():
    r = critique.critique(_bold_icon())
    for key in ("score", "verdict", "tips", "recommend", "signals"):
        assert key in r
    assert isinstance(r["tips"], list) and r["tips"]
    # recommends a buildable minimum size and the plan-shaping toggles
    assert r["recommend"]["min_size_m"] > 0
    assert set(("dither", "thicken", "preset")) <= set(r["recommend"])


def test_low_contrast_is_flagged_in_tips():
    r = critique.critique(_busy_lowcontrast())
    assert any("contrast" in t.lower() for t in r["tips"])
