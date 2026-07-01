"""Perception + projector geometry math (pure, no I/O).

Two independent things decide how a finished piece looks:

1. **Geometry.** A fixed-throw projector at height H paints width ``H/throw``;
   with cap pitch ``p`` that gives ``W/p`` caps across — the real resolution.
2. **Perception.** Physical size doesn't change perceived detail, only how far
   back you stand. A cap of pitch ``p`` at distance ``d`` subtends ``p/d``; below
   ~3 arcmin tiles look smooth, and a picture already "reads" once a cap subtends
   roughly 25 arcmin (the brain integrates coarse tiles into an image).

Lives in ``core`` so both the sizing report (``app.sizing``) and the estimator
(``core.estimator``) share one source of truth.
"""

from __future__ import annotations

import math

ARCMIN_PER_RAD = 60.0 * 180.0 / math.pi  # 3437.75

# Cap subtends ~this many arc-minutes -> the mosaic reads as a coherent picture.
READS_ARCMIN = 25.0
# Cap subtends ~this many arc-minutes -> tiles are essentially smooth/indistinct.
SMOOTH_ARCMIN = 3.0


def image_width_m(mount_height_m: float, throw_ratio: float) -> float:
    """Projected image width for a fixed-throw projector at a given height."""
    return mount_height_m / throw_ratio


def angular_arcmin(size_m: float, distance_m: float) -> float:
    return (size_m / distance_m) * ARCMIN_PER_RAD


def distance_for_arcmin(size_m: float, arcmin: float) -> float:
    return size_m / (arcmin / ARCMIN_PER_RAD)


def fov_distance(width_m: float, horizontal_fov_deg: float) -> float:
    """Distance at which `width_m` fills the given horizontal field of view."""
    return (width_m / 2.0) / math.tan(math.radians(horizontal_fov_deg / 2.0))
