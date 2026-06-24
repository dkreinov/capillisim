"""White / logoed-cap reading + presence detection on the Cap Reading Card.

These synthesize a card frame (via render_card) with a cap drawn in the
placement circle, so the colour/presence stages are exercised headless.
"""

import numpy as np
from PIL import ImageDraw

from cap_mosaic.app.make_card import render_card
from cap_mosaic.core.palette import ciede2000, rgb_to_lab
from cap_mosaic.vision import card_layout as L
from cap_mosaic.vision.card_reader import (
    cap_present,
    detect_card,
    read_cap_color,
    read_cap_field,
    white_balance,
)


def _card_with_cap(field_rgb, logo_rgb=None, logo_frac=0.0, dpi=200):
    """Render the card with a filled cap disc and an optional centred logo blob.

    `logo_frac` is the logo blob's radius as a fraction of the cap radius.
    Returns the RGB frame (numpy) and the cap centre/radius in pixels.
    """
    ppm = dpi / 25.4
    card = render_card(dpi).copy()
    draw = ImageDraw.Draw(card)
    cx, cy = L.CIRCLE_CX_MM * ppm, L.CIRCLE_CY_MM * ppm
    r = L.CIRCLE_R_MM * ppm * 0.85
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(field_rgb))
    if logo_rgb is not None and logo_frac > 0:
        lr = r * logo_frac
        draw.ellipse([cx - lr, cy - lr, cx + lr, cy + lr], fill=tuple(logo_rgb))
    return np.asarray(card), (cx, cy, r)


def test_glare_majority_keeps_field_not_logo():
    # A bright white cap (mostly > glare level) with a small dark logo: the read
    # must return the white field, not the dark logo the glare mask leaves behind.
    field = (250, 250, 250)
    frame, _ = _card_with_cap(field, logo_rgb=(20, 20, 20), logo_frac=0.25)
    h = detect_card(frame)
    assert h is not None
    got = read_cap_color(white_balance(frame, h), h)
    assert got is not None
    de = ciede2000(rgb_to_lab(got), rgb_to_lab(field))
    assert de < 12, (got, de)


def test_read_field_excludes_logo_and_reports_marking():
    # White field + a red 'SB'-like blob covering ~35% radius (~12% area).
    field = (235, 235, 235)
    frame, _ = _card_with_cap(field, logo_rgb=(200, 40, 40), logo_frac=0.5)
    h = detect_card(frame)
    out = read_cap_field(white_balance(frame, h), h)
    assert out is not None
    field_rgb, marking_frac, spread = out
    # the stored colour is the white field, not a pink average
    de = ciede2000(rgb_to_lab(field_rgb), rgb_to_lab(field))
    assert de < 12, (field_rgb, de)
    # a logo is present -> non-trivial marking fraction and high field/logo spread
    assert 0.05 < marking_frac < 0.6, marking_frac
    assert spread > 20, spread


def test_read_field_uniform_cap_has_near_zero_marking():
    field = (60, 110, 170)  # plain blue cap, no logo
    frame, _ = _card_with_cap(field)
    h = detect_card(frame)
    out = read_cap_field(white_balance(frame, h), h)
    assert out is not None
    field_rgb, marking_frac, _ = out
    assert ciede2000(rgb_to_lab(field_rgb), rgb_to_lab(field)) < 12
    assert marking_frac < 0.1, marking_frac


def test_presence_empty_circle_is_absent():
    # render_card with no cap drawn -> the printed white circle is "empty"
    ppm = 200 / 25.4
    from cap_mosaic.app.make_card import render_card

    frame = np.asarray(render_card(200))
    h = detect_card(frame)
    assert h is not None
    assert cap_present(frame, h) is False


def test_presence_white_logo_cap_is_detected():
    field = (235, 235, 235)
    frame, _ = _card_with_cap(field, logo_rgb=(200, 40, 40), logo_frac=0.5)
    h = detect_card(frame)
    assert cap_present(frame, h) is True


def test_presence_uniform_colored_cap_is_detected():
    frame, _ = _card_with_cap((60, 110, 170))  # plain blue, saturated
    h = detect_card(frame)
    assert cap_present(frame, h) is True
