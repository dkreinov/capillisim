"""Card detection: recover canonical points from a perspective-warped card image."""

import cv2
import numpy as np

from cap_mosaic.app.make_card import render_card
from cap_mosaic.vision import card_layout as L
from cap_mosaic.vision.card_reader import card_mm_to_px, detect_card


def test_detect_recovers_points_under_perspective():
    dpi = 200
    ppm = dpi / 25.4
    card = render_card(dpi)
    cw, ch = card.size
    arr = np.asarray(card)  # RGB

    # warp the rendered card onto a larger canvas with an arbitrary perspective
    src = np.float32([[0, 0], [cw, 0], [cw, ch], [0, ch]])
    dst = np.float32([[180, 120], [cw + 240, 60], [cw + 330, ch + 230], [120, ch + 280]])
    hwarp = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(arr, hwarp, (cw + 500, ch + 460), borderValue=(255, 255, 255))

    h = detect_card(warped)
    assert h is not None

    points_mm = [(L.CIRCLE_CX_MM, L.CIRCLE_CY_MM)] + [(m.cx_mm, m.cy_mm) for m in L.MARKERS]
    for x_mm, y_mm in points_mm:
        truth = hwarp @ np.array([x_mm * ppm, y_mm * ppm, 1.0])
        tx, ty = truth[0] / truth[2], truth[1] / truth[2]
        gx, gy = card_mm_to_px(h, x_mm, y_mm)
        assert abs(gx - tx) < 4 and abs(gy - ty) < 4, (x_mm, y_mm, gx, gy, tx, ty)


def test_no_card_returns_none():
    blank = np.full((300, 400, 3), 200, np.uint8)
    assert detect_card(blank) is None
