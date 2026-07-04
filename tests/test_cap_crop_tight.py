"""Tight cap cutouts: the circle must hug the cap's metal edge.

Glued caps meet edge to edge, so a cutout padded with card white (or dragged
off-centre by a shadow) shows as fake gaps in every rendered mosaic. These
cases mirror observed failures of Hough + ring-walk on real dataset crops.
"""

from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from cap_mosaic.app.cap_crop import cap_cutout

TOL = 0.06  # cutout radius must match the true cap edge within ~6%


def _scene(cap_r=40, centre=(64, 64), shadow=None, ring=False, logo=None,
           size=128):
    """White card with a dark cap disc; optional shadow lobe / printed ring /
    white logo. Returns the BGR image and the true cap geometry."""
    img = np.full((size, size, 3), 245, np.uint8)
    cx, cy = centre
    if ring:
        cv2.circle(img, (size // 2, size // 2), int(size * 0.44), (150, 150, 150), 2)
    if shadow is not None:  # a soft cast-shadow lobe attached to one side
        sx, sy, sr = shadow
        cv2.ellipse(img, (sx, sy), (sr, int(sr * 0.7)), 30, 0, 360, (120, 118, 115), -1)
    cv2.circle(img, (cx, cy), cap_r, (30, 40, 110), -1)
    cv2.circle(img, (cx, cy), cap_r, (15, 15, 15), 2)
    if logo is not None:  # white marking inside the cap
        kind, arg = logo
        if kind == "disc":
            cv2.circle(img, (cx, cy), int(cap_r * arg), (240, 240, 240), -1)
        else:  # ring of white text
            cv2.circle(img, (cx, cy), int(cap_r * arg), (240, 240, 240),
                       int(cap_r * 0.18))
    return img, (cx, cy, cap_r)


def _cutout_error(img, truth, size=96):
    """Fractional radius error of the cutout vs the true cap edge.

    The cutout maps a source circle (centre c, radius r) onto `size` px. We
    recover r by checking, per direction, where cap pixels stop inside the
    cutout: if the crop is loose, cap pixels stop well short of the cutout
    edge; if perfectly tight they reach it.
    """
    cut = np.asarray(cap_cutout(img, size)).astype(int)
    rgb, alpha = cut[..., :3], cut[..., 3]
    inside = alpha > 0
    capish = inside & ~((rgb >= 200).all(axis=2))  # not card-white / not blank
    ys, xs = np.nonzero(capish)
    if ys.size == 0:
        return 1.0
    c = size / 2 - 0.5
    r = np.hypot(xs - c, ys - c)
    bins = (np.degrees(np.arctan2(ys - c, xs - c)) % 360).astype(int)
    rmax = np.zeros(360)
    np.maximum.at(rmax, bins, r)
    cov = rmax > 0
    if cov.sum() < 270:
        return 1.0
    reach = np.median(rmax[cov]) / (size / 2)  # 1.0 == cap fills the cutout
    return abs(1.0 - reach)


def test_tight_when_clean():
    img, truth = _scene()
    assert _cutout_error(img, truth) < TOL


def test_tight_when_cap_off_centre():
    img, truth = _scene(centre=(50, 76))
    assert _cutout_error(img, truth) < TOL


def test_tight_despite_attached_shadow_lobe():
    # shadow overlaps the cap's right edge — centre/radius must ignore it
    img, truth = _scene(cap_r=36, shadow=(104, 76, 30))
    assert _cutout_error(img, truth) < TOL


def test_tight_despite_printed_card_circle():
    img, truth = _scene(cap_r=34, ring=True)
    assert _cutout_error(img, truth) < TOL


def test_tight_despite_white_text_ring():
    img, truth = _scene(logo=("ring", 0.55))
    assert _cutout_error(img, truth) < TOL


def test_tight_despite_big_white_logo():
    img, truth = _scene(logo=("disc", 0.45))
    assert _cutout_error(img, truth) < TOL


def test_white_cap_not_overshrunk_to_its_logo():
    # a WHITE cap on the white card: face brighter than the 215 white cut,
    # only a faint rim and a small logo are 'visible'. The old blob fallback
    # saw just the logo and zoomed the cutout into it (real Hoegaarden case).
    size = 128
    img = np.full((size, size, 3), 245, np.uint8)
    cv2.circle(img, (64, 64), 42, (238, 238, 238), -1)   # white face
    cv2.circle(img, (64, 64), 42, (205, 205, 208), 3)    # faint rim
    cv2.circle(img, (64, 64), 12, (150, 60, 40), -1)     # small blue logo
    cut = np.asarray(cap_cutout(img, 96)).astype(int)
    inside = cut[..., 3] > 0
    logoish = inside & (np.abs(cut[..., :3] - [150, 60, 40]).sum(axis=2) < 40)
    # if the cutout zoomed into the logo, the logo dominates the tile
    assert logoish.sum() / inside.sum() < 0.10, logoish.sum() / inside.sum()
    # and the faint rim must sit near the cutout edge (cap edge included)
    ys, xs = np.nonzero(inside & (np.abs(cut[..., :3] - [205, 205, 208]).sum(axis=2) < 30))
    assert ys.size > 0
    r = np.hypot(xs - 47.5, ys - 47.5)
    assert r.max() > 0.85 * 48, r.max()


def test_corner_cap_stays_round_not_squished():
    # cap near the frame edge: the old crop box clamped at the border and the
    # square resize squished the cap into an ellipse
    size = 128
    img = np.full((size, size, 3), 245, np.uint8)
    cv2.circle(img, (16, 64), 28, (30, 40, 110), -1)
    cut = np.asarray(cap_cutout(img, 96)).astype(int)
    inside = cut[..., 3] > 0
    capish = inside & ~((cut[..., :3] >= 200).all(axis=2))
    ys, xs = np.nonzero(capish)
    assert ys.size > 0
    c = 47.5
    r = np.hypot(xs - c, ys - c)
    bins = (np.degrees(np.arctan2(ys - c, xs - c)) % 360).astype(int)
    rmax = np.zeros(360)
    np.maximum.at(rmax, bins, r)
    cov = rmax[rmax > 0]
    assert cov.size >= 270
    # round: the edge radius must not vary like a squished ellipse would
    assert np.percentile(cov, 10) / np.percentile(cov, 90) > 0.85


FIXTURES = Path(__file__).parent / "fixtures"


def _roundness(path: Path) -> float:
    """p10/p90 of the cutout content's edge radius — 1.0 = centred circle.

    Off-centre or lopsided cutouts (real dataset failures) score low: the
    content reaches the tile edge on one side and stops short on the other.
    """
    img = cv2.imread(str(path))
    assert img is not None
    cut = np.asarray(cap_cutout(img, 96)).astype(int)
    inside = cut[..., 3] > 0
    capish = inside & ~((cut[..., :3] >= 210).all(axis=2))
    ys, xs = np.nonzero(capish)
    assert ys.size > 0
    c = 47.5
    r = np.hypot(xs - c, ys - c)
    bins = (np.degrees(np.arctan2(ys - c, xs - c)) % 360).astype(int)
    rmax = np.zeros(360)
    np.maximum.at(rmax, bins, r)
    cov = rmax[rmax > 0]
    assert cov.size >= 250
    return float(np.percentile(cov, 10) / max(1.0, np.percentile(cov, 90)))


def test_real_white_cap_centred_and_round():
    # real Hoegaarden-style white cap: blob fallback used to lock onto the
    # logo/shadow and produce a lopsided cutout (was 0.70)
    assert _roundness(FIXTURES / "white_cap_overzoom.png") > 0.80


def test_real_corner_cap_centred_and_round():
    # real cap photographed near the crop corner: was squished/off-centre (0.31)
    assert _roundness(FIXTURES / "corner_cap_offcentre.png") > 0.80


def test_real_shadow_cap_stays_good():
    # regression guard: this real cap with a soft shadow is already handled
    assert _roundness(FIXTURES / "shadow_lobe_cap.png") > 0.80


def test_no_cap_falls_back_gracefully():
    img = np.full((128, 128, 3), 245, np.uint8)  # bare card, nothing to find
    cut = cap_cutout(img, 64)
    assert cut.size == (64, 64)  # never crashes, still returns an RGBA tile
