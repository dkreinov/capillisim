import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from cap_mosaic.app.cap_crop import cap_cutout, detect_cap_circle


def _cap_on_white(n=128, cx=44, cy=52, r=28, color=(40, 60, 200)):
    """A BGR image: an off-centre coloured disc (with a dark rim) on white."""
    img = np.full((n, n, 3), 255, np.uint8)
    cv2.circle(img, (cx, cy), r, color, -1)             # BGR fill
    cv2.circle(img, (cx, cy), r, (30, 30, 30), 3)       # dark crimped rim
    return img


def test_detects_offcentre_cap():
    img = _cap_on_white(cx=44, cy=52, r=28)
    c = detect_cap_circle(img)
    assert c is not None
    cx, cy, r = c
    assert abs(cx - 44) <= 6 and abs(cy - 52) <= 6
    assert abs(r - 28) <= 8


def test_cutout_is_centred_and_circular():
    img = _cap_on_white(cx=44, cy=52, r=28, color=(40, 60, 200))
    out = cap_cutout(img, size=64)
    assert out.size == (64, 64) and out.mode == "RGBA"
    a = np.asarray(out)
    # centre is the cap colour: BGR fill (40,60,200) -> RGB (200,60,40), opaque
    r, g, b, alpha = a[32, 32]
    assert alpha == 255 and r > 150 and b < 120
    # corners are outside the circle -> transparent
    assert a[0, 0, 3] == 0 and a[63, 63, 3] == 0


def test_cutout_handles_blank_image():
    blank = np.full((100, 100, 3), 255, np.uint8)
    out = cap_cutout(blank, size=48)  # no cap -> falls back to centre disc
    assert out.size == (48, 48)
