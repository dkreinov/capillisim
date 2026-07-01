"""Estimator: the coupled size <-> distance <-> caps relationship.

Caps are a fixed physical size, so a mosaic is a heavy downsampling of the target
and only reads once you stand far enough that caps blend into a picture. This
module ties three things together:

- **Legibility floor** (`core.legibility`): the minimum caps-across for the
  subject to be representable at all. Below it, no distance helps.
- **Perception** (`core.sizing`): how far a cap must be to stop being visible
  (blend distance), and how big a piece must be to fill a comfortable field of
  view at a given distance.
- **Shade merging**: far away, near colours blend, so the effective palette
  shrinks with distance.

Two-way: give a physical size -> get the minimum viewing distance (or a warning
that it's too few caps); give a distance -> get the required size. Pure core.
"""

from __future__ import annotations

import math

import numpy as np

from . import sizing
from .geometry import Cap, estimate_count
from .legibility import min_caps_across
from .palette import RGB, ciede2000, rgb_to_lab

DEFAULT_FOV_DEG = 28.0  # a piece "fills the view" at roughly this horizontal FOV
JND_DE = 2.3  # baseline just-noticeable CIEDE2000 colour difference (close up)


def blend_distance_m(pitch_mm: float = 32.0) -> float:
    """Distance beyond which individual caps stop being resolvable (they blend)."""
    return sizing.distance_for_arcmin(pitch_mm / 1000.0, sizing.READS_ARCMIN)


def read_quality(pitch_mm: float, distance_m: float) -> str:
    """'caps' (individually visible) | 'reads' (as a picture) | 'smooth' (indistinct)."""
    arcmin = sizing.angular_arcmin(pitch_mm / 1000.0, distance_m)
    if arcmin > sizing.READS_ARCMIN:
        return "caps"
    if arcmin > sizing.SMOOTH_ARCMIN:
        return "reads"
    return "smooth"


def solve_from_size(
    image_rgb: np.ndarray,
    width_mm: float,
    *,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    fov_deg: float = DEFAULT_FOV_DEG,
    min_caps: int | None = None,
) -> dict:
    """Given a physical width, report caps, legibility, and viewing distances.

    Pass ``min_caps`` to reuse a precomputed legibility floor (it depends only on
    the image + mode, so callers can cache it across sizes)."""
    a = np.asarray(image_rgb)
    h, w = a.shape[:2]
    aspect = w / h
    cap = Cap(pitch_mm)
    caps_across = int(width_mm // pitch_mm)
    floor = min_caps if min_caps is not None else min_caps_across(a, mode=mode, aspect=aspect)
    legible = caps_across >= floor
    height_mm = width_mm / aspect
    total = estimate_count(width_mm, height_mm, cap)
    d_blend = blend_distance_m(pitch_mm)
    d_fov = sizing.fov_distance(width_mm / 1000.0, fov_deg)
    warning = None
    if not legible:
        need_m = floor * pitch_mm / 1000.0
        warning = (
            f"Too few caps at this size ({caps_across} < {floor} needed). Make it "
            f"at least {need_m:.1f} m wide (or use Pattern mode) to represent this "
            f"image — any image is representable given enough caps."
        )
    return {
        "width_mm": round(width_mm, 1),
        "height_mm": round(height_mm, 1),
        "aspect": aspect,
        "caps_across": caps_across,
        "min_caps_across": floor,
        "total_caps": total,
        "legible": legible,
        "min_distance_m": round(d_blend, 2),
        "recommended_distance_m": round(max(d_blend, d_fov), 2),
        "warning": warning,
    }


def solve_from_distance(
    image_rgb: np.ndarray,
    distance_m: float,
    *,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    fov_deg: float = DEFAULT_FOV_DEG,
    min_caps: int | None = None,
) -> dict:
    """Given a viewing distance, report the size that fills the view and its caps."""
    width_mm = 2.0 * distance_m * math.tan(math.radians(fov_deg / 2.0)) * 1000.0
    res = solve_from_size(
        image_rgb, width_mm, mode=mode, pitch_mm=pitch_mm, fov_deg=fov_deg,
        min_caps=min_caps,
    )
    res["distance_m"] = round(distance_m, 2)
    res["read_quality"] = read_quality(pitch_mm, distance_m)
    if distance_m < res["min_distance_m"]:
        extra = (
            f" At {distance_m:.1f} m individual caps are visible; move back to "
            f"~{res['min_distance_m']:.1f} m to see the picture."
        )
        res["warning"] = (res["warning"] or "").strip() + extra if res["warning"] else extra.strip()
    return res


def merge_tolerance(distance_m: float, pitch_mm: float = 32.0) -> float:
    """CIEDE2000 below which two cap colours blend at this distance (grows with distance)."""
    arcmin = sizing.angular_arcmin(pitch_mm / 1000.0, distance_m)
    return JND_DE * (sizing.READS_ARCMIN / max(arcmin, 0.5))


def effective_colors(
    palette: list[RGB], distance_m: float, pitch_mm: float = 32.0
) -> list[RGB]:
    """The palette as it reads at `distance_m` — near shades merge, so it shrinks."""
    tol = merge_tolerance(distance_m, pitch_mm)
    reps: list[tuple[RGB, tuple]] = []
    for c in palette:
        lab = rgb_to_lab(tuple(c))
        if all(ciede2000(lab, r_lab) >= tol for _, r_lab in reps):
            reps.append((c, lab))
    return [c for c, _ in reps]
