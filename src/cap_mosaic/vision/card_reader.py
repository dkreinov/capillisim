"""Card-driven cap reader.

Locate the printed Cap Reading Card by its ArUco corners, white-balance the frame
from the gray strip, crop the cap from the known circle, and read a robust,
illumination-corrected colour. Pure numpy/OpenCV so the geometry/colour stages
test headless; the live capture loop lives in ``app.card_build``.

Frames are RGB numpy arrays (H, W, 3) uint8 — matching PIL decoding and the
``core.palette`` colour functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..core.palette import RGB, Lab, ciede2000, rgb_to_lab
from . import card_layout as L

GLARE_LEVEL = 240  # pixels brighter than this in all channels are treated as glare
MARKING_MIN_DE = 8.0  # field/marking clusters closer than this -> cap is one colour

# Presence detection (a cap can't be told from the white card circle by
# brightness alone). A real cap adds colour (saturated pixels) and/or texture
# (luma variance); the empty printed circle is flat white with a thin gray
# crosshair. Tuned on synthetic frames; expose via the capture preview for rig
# calibration. NOTE: a perfectly plain matte-white cap with no marking is still
# ambiguous here — the gray placement-circle card option is the fix for that.
SAT_LEVEL = 40  # per-pixel (max-min) above which a pixel counts as coloured
SAT_FRAC = 0.10  # fraction of coloured inner pixels that signals a cap
STD_LEVEL = 18.0  # inner-circle luma std above which texture signals a cap

_DETECTOR: "cv2.aruco.ArucoDetector | None" = None


def _detector() -> "cv2.aruco.ArucoDetector":
    global _DETECTOR
    if _DETECTOR is None:
        adict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, L.ARUCO_DICT))
        p = cv2.aruco.DetectorParameters()
        # tuned for small / slightly blurry markers from a webcam
        p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        p.adaptiveThreshWinSizeMin = 3
        p.adaptiveThreshWinSizeMax = 23
        p.adaptiveThreshWinSizeStep = 4
        p.minMarkerPerimeterRate = 0.015
        _DETECTOR = cv2.aruco.ArucoDetector(adict, p)
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
    present = [m for m in L.MARKERS if m.id in by_id]
    if len(present) < 3:  # 3 corner markers still span the card for a homography
        return None
    half = L.MARKER_SIZE_MM / 2
    src, dst = [], []
    for m in present:
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


def _inner_circle_pixels(
    rgb: np.ndarray, h: np.ndarray, frac: float = 0.70
) -> np.ndarray | None:
    """Pixels inside the inner `frac` of the placement circle (Nx3), or None."""
    cx, cy, r = _region_px(h, L.CIRCLE_CX_MM, L.CIRCLE_CY_MM, L.CIRCLE_R_MM)
    inner = r * frac
    img_h, img_w = rgb.shape[:2]
    y0, y1 = max(0, int(cy - inner)), min(img_h, int(cy + inner) + 1)
    x0, x1 = max(0, int(cx - inner)), min(img_w, int(cx + inner) + 1)
    if y1 <= y0 or x1 <= x0:
        return None
    crop = rgb[y0:y1, x0:x1].reshape(-1, 3)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    circle = ((xx - cx) ** 2 + (yy - cy) ** 2 <= inner**2).reshape(-1)
    pixels = crop[circle]
    return pixels if pixels.size else None


def _deglare(pixels: np.ndarray, glare_level: int) -> np.ndarray:
    """Drop bright (glare) pixels, but only when they're a minority.

    A mostly-bright cap (e.g. white) really is bright — masking it would leave
    only the dark leftovers (its own logo/shadows) and read the wrong colour.
    """
    not_glare = ~np.all(pixels > glare_level, axis=1)
    return pixels[not_glare] if not_glare.mean() > 0.5 else pixels


def read_cap_color(
    rgb: np.ndarray, h: np.ndarray, glare_level: int = GLARE_LEVEL
) -> RGB | None:
    """Robust dominant colour of the cap in the placement circle, or None.

    Samples the inner 70% of the circle (avoiding the printed outline), masks
    specular glare, and returns the median colour. Run on a white-balanced frame.
    """
    pixels = _inner_circle_pixels(rgb, h)
    if pixels is None:
        return None
    med = np.median(_deglare(pixels, glare_level), axis=0)
    return (int(med[0]), int(med[1]), int(med[2]))


def read_cap_field(
    rgb: np.ndarray, h: np.ndarray, glare_level: int = GLARE_LEVEL
) -> tuple[RGB, float, float] | None:
    """Dominant *field* colour of the cap, separated from any logo/marking.

    Splits the inner-circle pixels into two colour clusters (k-means in Lab) and
    returns ``(field_rgb, marking_frac, spread)`` — the larger cluster's mean
    colour, the fraction of pixels in the smaller (marking) cluster, and the
    CIEDE2000 separation between them. When the two clusters are nearly the same
    colour the cap is treated as a single flat colour (marking_frac = 0). Run on
    a white-balanced frame. See docs/COLOR_MATCHING.md (dominant-field reading).
    """
    pixels = _inner_circle_pixels(rgb, h)
    if pixels is None:
        return None
    px = _deglare(pixels, glare_level).astype(np.uint8)
    if len(px) < 2:
        med = np.median(px, axis=0)
        return (int(med[0]), int(med[1]), int(med[2])), 0.0, 0.0

    lab = cv2.cvtColor(px.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, _ = cv2.kmeans(
        lab.astype(np.float32), 2, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    labels = labels.flatten()
    counts = np.bincount(labels, minlength=2)
    big = int(np.argmax(counts))
    field = px[labels == big].mean(0)
    field_rgb = (int(field[0]), int(field[1]), int(field[2]))
    other = px[labels == (1 - big)].mean(0)
    other_rgb = (int(other[0]), int(other[1]), int(other[2]))
    spread = ciede2000(rgb_to_lab(field_rgb), rgb_to_lab(other_rgb))
    if spread < MARKING_MIN_DE:  # one colour: the split is just noise
        med = np.median(px, axis=0)
        return (int(med[0]), int(med[1]), int(med[2])), 0.0, float(spread)
    marking_frac = float(counts[1 - big] / counts.sum())
    return field_rgb, marking_frac, float(spread)


def presence_metrics(rgb: np.ndarray, h: np.ndarray) -> tuple[float, float] | None:
    """(coloured-pixel fraction, luma std) inside the placement circle, or None."""
    px = _inner_circle_pixels(rgb, h)
    if px is None:
        return None
    px = px.astype(np.int16)
    sat = px.max(1) - px.min(1)
    return float((sat > SAT_LEVEL).mean()), float(px.mean(1).std())


def cap_present(
    rgb: np.ndarray,
    h: np.ndarray,
    sat_frac: float = SAT_FRAC,
    std_level: float = STD_LEVEL,
) -> bool:
    """True if a cap is on the card — by colour/texture, not brightness.

    A white cap reads as bright as the empty white circle, so brightness can't
    decide presence. Instead, a cap shows colour (saturated pixels) and/or
    texture (luma variance) that the flat printed circle lacks.
    """
    m = presence_metrics(rgb, h)
    if m is None:
        return False
    frac, std = m
    return bool(frac > sat_frac or std > std_level)


def crop_cap(rgb: np.ndarray, h: np.ndarray, size: int = 128) -> np.ndarray | None:
    """Fixed-size square crop of the cap from the placement circle, or None.

    Pass a white-balanced frame to get colour-consistent dataset images. Crops a
    little past the circle and resizes to ``size`` x ``size``.
    """
    cx, cy, r = _region_px(h, L.CIRCLE_CX_MM, L.CIRCLE_CY_MM, L.CIRCLE_R_MM)
    s = max(1, int(r * 1.05))
    img_h, img_w = rgb.shape[:2]
    y0, y1 = max(0, int(cy - s)), min(img_h, int(cy + s))
    x0, x1 = max(0, int(cx - s)), min(img_w, int(cx + s))
    if y1 <= y0 or x1 <= x0:
        return None
    return cv2.resize(rgb[y0:y1, x0:x1], (size, size), interpolation=cv2.INTER_AREA)


@dataclass(frozen=True)
class CapReading:
    rgb: RGB
    lab: Lab


class CardCapReader:
    """End-to-end: locate card -> white-balance -> read the cap colour.

    ``read(rgb_frame)`` returns a :class:`CapReading` when the card is found, or
    ``None`` when no card is visible. Cap colour is already illumination-corrected.

    The card sits still under the camera, so a one-frame detection miss (motion
    blur, a brief occlusion) shouldn't blank the reading. With ``hold_frames`` >
    0, the last good card homography is reused for up to that many consecutive
    misses before giving up — smoothing the flicker.
    """

    def __init__(self, glare_level: int = GLARE_LEVEL, hold_frames: int = 0):
        self.glare_level = glare_level
        self.hold_frames = hold_frames
        self._last_h: np.ndarray | None = None
        self._miss = 0

    def read(self, rgb_frame: np.ndarray) -> "CapReading | None":
        h = detect_card(rgb_frame)
        if h is not None:
            self._last_h, self._miss = h, 0
        elif self._last_h is not None and self._miss < self.hold_frames:
            self._miss += 1
            h = self._last_h
        else:
            self._last_h = None
            return None
        corrected = white_balance(rgb_frame, h)
        rgb = read_cap_color(corrected, h, self.glare_level)
        if rgb is None:
            return None
        return CapReading(rgb=rgb, lab=rgb_to_lab(rgb))
