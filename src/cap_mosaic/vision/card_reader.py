"""Card-driven cap reader.

Locate the printed Cap Reading Card by its ArUco corners, white-balance the frame
from the gray strip, crop the cap from the known circle, and read a robust,
illumination-corrected colour. Pure numpy/OpenCV so the geometry/colour stages
test headless; the live capture loop lives in ``app.card_build``.

Frames are RGB numpy arrays (H, W, 3) uint8 — matching PIL decoding and the
``core.palette`` colour functions.
"""

from __future__ import annotations

import cv2
import numpy as np

from . import card_layout as L

_DETECTOR: "cv2.aruco.ArucoDetector | None" = None


def _detector() -> "cv2.aruco.ArucoDetector":
    global _DETECTOR
    if _DETECTOR is None:
        adict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, L.ARUCO_DICT))
        _DETECTOR = cv2.aruco.ArucoDetector(adict, cv2.aruco.DetectorParameters())
    return _DETECTOR


def detect_card(rgb: np.ndarray) -> np.ndarray | None:
    """Homography mapping card millimetres -> image pixels, or None if not found.

    Uses all four corners of every marker (16 correspondences) for a robust,
    least-squares fit.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    corners, ids, _ = _detector().detectMarkers(gray)
    if ids is None:
        return None
    by_id = {int(i): c.reshape(4, 2) for c, i in zip(corners, ids.flatten())}
    if not {m.id for m in L.MARKERS}.issubset(by_id):
        return None
    half = L.MARKER_SIZE_MM / 2
    src, dst = [], []
    for m in L.MARKERS:
        # ArUco corner order is TL, TR, BR, BL in the (upright) marker frame,
        # which matches these canonical card-mm corners.
        canon = [
            (m.cx_mm - half, m.cy_mm - half),
            (m.cx_mm + half, m.cy_mm - half),
            (m.cx_mm + half, m.cy_mm + half),
            (m.cx_mm - half, m.cy_mm + half),
        ]
        for cc, dc in zip(canon, by_id[m.id]):
            src.append(cc)
            dst.append(dc)
    h, _ = cv2.findHomography(np.asarray(src, np.float32), np.asarray(dst, np.float32))
    return h


def card_mm_to_px(h: np.ndarray, x_mm: float, y_mm: float) -> tuple[float, float]:
    """Map a card-millimetre point to image pixels via the card homography."""
    v = h @ np.array([x_mm, y_mm, 1.0])
    return (float(v[0] / v[2]), float(v[1] / v[2]))


def _region_px(h: np.ndarray, cx_mm: float, cy_mm: float, span_mm: float):
    """Pixel centre + radius for a card-mm point and an mm half-span."""
    cx, cy = card_mm_to_px(h, cx_mm, cy_mm)
    ex, ey = card_mm_to_px(h, cx_mm + span_mm, cy_mm)
    return cx, cy, float(np.hypot(ex - cx, ey - cy))


def _sample_median(rgb: np.ndarray, cx: float, cy: float, rad: float) -> np.ndarray:
    """Median RGB of the square region of half-size `rad` around (cx, cy)."""
    h, w = rgb.shape[:2]
    r = max(1, int(rad))
    y0, y1 = max(0, int(cy) - r), min(h, int(cy) + r + 1)
    x0, x1 = max(0, int(cx) - r), min(w, int(cx) + r + 1)
    return np.median(rgb[y0:y1, x0:x1].reshape(-1, 3), axis=0)


def white_balance(rgb: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Neutralize illumination using the gray strip.

    Fits a per-channel line mapping the observed gray values to their nominal
    neutral values, then applies it to the whole frame. This removes the
    illuminant colour cast and corrects exposure/tone (it does NOT correct the
    camera's hue response — that would need coloured reference chips).
    """
    obs, exp = [], []
    for g in L.GRAY_PATCHES:
        cx, cy, rad = _region_px(h, g.cx_mm, g.cy_mm, L.GRAY_SIZE_MM * 0.30)
        obs.append(_sample_median(rgb, cx, cy, rad))
        exp.append([g.value, g.value, g.value])
    obs = np.asarray(obs, float)
    exp = np.asarray(exp, float)
    out = rgb.astype(np.float32)
    for c in range(3):
        a, b = np.polyfit(obs[:, c], exp[:, c], 1)
        out[..., c] = a * out[..., c] + b
    return np.clip(out, 0, 255).astype(np.uint8)
