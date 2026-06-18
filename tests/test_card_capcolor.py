"""Cap colour read: a known disc under a color cast is recovered within a small dE."""

import numpy as np
from PIL import ImageDraw

from cap_mosaic.app.make_card import render_card
from cap_mosaic.core.palette import ciede2000, rgb_to_lab
from cap_mosaic.vision import card_layout as L
from cap_mosaic.vision.card_reader import detect_card, read_cap_color, white_balance


def test_read_cap_color_illumination_corrected():
    dpi = 200
    ppm = dpi / 25.4
    card = render_card(dpi).copy()
    draw = ImageDraw.Draw(card)
    true_rgb = (90, 150, 200)  # sky blue cap
    cx, cy = L.CIRCLE_CX_MM * ppm, L.CIRCLE_CY_MM * ppm
    r = L.CIRCLE_R_MM * ppm * 0.85
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=true_rgb)

    casted = np.clip(np.asarray(card).astype(np.float32) * np.array([0.9, 0.8, 0.7]), 0, 255).astype(np.uint8)
    h = detect_card(casted)
    assert h is not None

    corrected = white_balance(casted, h)
    got = read_cap_color(corrected, h)
    assert got is not None

    de = ciede2000(rgb_to_lab(got), rgb_to_lab(true_rgb))
    assert de < 10, (got, true_rgb, de)
