"""White-balance: a color cast on the card is neutralized by the gray strip."""

import numpy as np

from cap_mosaic.app.make_card import render_card
from cap_mosaic.vision import card_layout as L
from cap_mosaic.vision.card_reader import (
    _region_px,
    _sample_median,
    detect_card,
    white_balance,
)


def test_white_balance_neutralizes_cast():
    arr = np.asarray(render_card(dpi=200)).astype(np.float32)
    # darkening colour cast (no clipping): R*0.9, G*0.8, B*0.7
    cast = np.array([0.9, 0.8, 0.7])
    casted = np.clip(arr * cast, 0, 255).astype(np.uint8)

    h = detect_card(casted)
    assert h is not None

    # before WB the grays are NOT neutral (cast skews channels)
    g_ref = L.GRAY_PATCHES[1]  # value 192
    cx, cy, rad = _region_px(h, g_ref.cx_mm, g_ref.cy_mm, L.GRAY_SIZE_MM * 0.30)
    before = _sample_median(casted, cx, cy, rad)
    assert float(before.max() - before.min()) > 20  # clearly cast

    corrected = white_balance(casted, h)

    for g in L.GRAY_PATCHES:
        cx, cy, rad = _region_px(h, g.cx_mm, g.cy_mm, L.GRAY_SIZE_MM * 0.30)
        m = _sample_median(corrected, cx, cy, rad)
        assert float(m.max() - m.min()) < 12, ("not neutral", g.value, m)
        assert abs(float(m.mean()) - g.value) < 25, ("tone off", g.value, m)
