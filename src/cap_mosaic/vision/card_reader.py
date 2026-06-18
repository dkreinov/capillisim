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
