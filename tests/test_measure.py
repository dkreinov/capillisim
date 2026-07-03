import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from cap_mosaic.vision import card_layout as L
from cap_mosaic.vision.card_reader import measure_cap_diameter_mm


def _frame(scale=4.0, cap_mm=None, printed_ring=True, size=(900, 900)):
    """Synthetic white frame at `scale` px/mm with an optional dark cap disc."""
    h = np.array([[scale, 0, 60.0], [0, scale, 60.0], [0, 0, 1.0]])
    img = np.full((*size, 3), 250, np.uint8)
    cx = int(L.CIRCLE_CX_MM * scale + 60)
    cy = int(L.CIRCLE_CY_MM * scale + 60)
    if printed_ring:  # the thin printed placement circle
        cv2.circle(img, (cx, cy), int(L.CIRCLE_R_MM * scale), (150, 150, 150), 2)
    if cap_mm:
        r = int(cap_mm / 2 * scale)
        cv2.circle(img, (cx, cy), r, (30, 40, 120), -1)      # cap body
        cv2.circle(img, (cx, cy), r, (20, 20, 20), 3)         # rim
    return img, h


def test_measures_a_standard_crown():
    img, h = _frame(cap_mm=26.0)
    d = measure_cap_diameter_mm(img, h)
    assert d is not None and abs(d - 26.0) < 1.5, d


def test_measures_a_large_cap():
    img, h = _frame(cap_mm=38.0)
    d = measure_cap_diameter_mm(img, h)
    assert d is not None and abs(d - 38.0) < 1.5, d


def test_empty_circle_returns_none():
    img, h = _frame(cap_mm=None)  # just the printed ring, no cap
    assert measure_cap_diameter_mm(img, h) is None


def test_works_at_a_different_camera_scale():
    img, h = _frame(scale=6.5, cap_mm=29.0)
    d = measure_cap_diameter_mm(img, h)
    assert d is not None and abs(d - 29.0) < 1.5, d
