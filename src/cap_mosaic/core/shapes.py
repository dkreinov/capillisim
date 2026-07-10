"""Non-rectangular mosaic outlines: masks over the hex grid.

A shape is a predicate over cell CENTRES in frame mm-coordinates. Cells whose
centre fails the mask are dropped from the Grid *before* planning, so palette
derivation, dithering, the BOM and the cap map never see outside-shape cells,
and `is_hole` keeps its single meaning ("wanted a cap, none available").
The grid's bounding width/height stay those of the enclosing rectangle.

Preset shapes are defined in normalized coordinates u, v in [-1, 1]
(u = (x - w/2)/(w/2), v = (y - h/2)/(h/2); y grows downward). The freeform
`poly` shape takes fractional (fx, fy) vertices of the frame, as drawn by the
user on the original image.
"""

from __future__ import annotations

import math
from typing import Callable

from .geometry import Grid

SHAPES = ("rect", "circle", "ellipse", "heart", "hex", "diamond", "poly")

# heart implicit curve (X^2 + Y^2 - 1)^3 - X^2*Y^3 <= 0, y flipped to screen
# coords; scale/offset place the lobes up and the tip just inside the frame.
_HEART_SCALE = 1.3
_HEART_LIFT = 0.25


def point_in_polygon(fx: float, fy: float,
                     pts: list[tuple[float, float]]) -> bool:
    """Even-odd ray casting (pnpoly). Vertices are fractional frame coords."""
    if len(pts) < 3:
        raise ValueError("a polygon needs at least 3 points")
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > fy) != (yj > fy) and \
                fx < (xj - xi) * (fy - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _heart(u: float, v: float) -> bool:
    x = _HEART_SCALE * u
    y = _HEART_SCALE * (-v) + _HEART_LIFT
    return (x * x + y * y - 1.0) ** 3 - x * x * y ** 3 <= 0.0


def shape_mask(
    shape: str,
    width_mm: float,
    height_mm: float,
    poly: list[tuple[float, float]] | None = None,
) -> Callable[[float, float], bool]:
    """(x_mm, y_mm) -> keep? for a shape inscribed in the width x height frame."""
    if shape not in SHAPES:
        raise ValueError(f"unknown shape {shape!r}; one of {SHAPES}")
    if shape == "poly":
        if not poly or len(poly) < 3:
            raise ValueError("shape 'poly' needs at least 3 (fx, fy) points")
        pts = list(poly)
        return lambda x, y: point_in_polygon(x / width_mm, y / height_mm, pts)
    if shape == "rect":
        return lambda x, y: True
    cx, cy = width_mm / 2.0, height_mm / 2.0

    def uv(x: float, y: float) -> tuple[float, float]:
        return (x - cx) / cx, (y - cy) / cy

    if shape == "circle":  # a TRUE circle of diameter min(w, h), centred
        r = min(cx, cy)
        return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    if shape == "ellipse":
        return lambda x, y: (lambda u, v: u * u + v * v <= 1.0)(*uv(x, y))
    if shape == "diamond":
        return lambda x, y: (lambda u, v: abs(u) + abs(v) <= 1.0)(*uv(x, y))
    if shape == "hex":  # flat top/bottom, vertices (+-1, 0) and (+-1/2, +-1)
        return lambda x, y: (
            lambda u, v: abs(v) <= 1.0 and 2.0 * abs(u) + abs(v) <= 2.0
        )(*uv(x, y))
    return lambda x, y: _heart(*uv(x, y))


def shape_area_fraction(
    shape: str, poly: list[tuple[float, float]] | None = None,
) -> float:
    """Fraction of the bounding rectangle the shape covers (for cap-count
    estimates). Analytic where possible; the heart is integrated numerically
    once; a polygon uses the shoelace formula on its fractional vertices."""
    if shape == "rect":
        return 1.0
    if shape in ("circle", "ellipse"):
        # the true circle covers pi/4 of its own square; against a non-square
        # frame the caller's estimate is per-bounding-box, so keep pi/4 — the
        # circle case is exact only for square frames (documented, small bias).
        return math.pi / 4.0
    if shape == "diamond":
        return 0.5
    if shape == "hex":
        return 0.75
    if shape == "heart":
        return _heart_fraction()
    if shape == "poly":
        if not poly or len(poly) < 3:
            raise ValueError("shape 'poly' needs at least 3 (fx, fy) points")
        area = 0.0
        j = len(poly) - 1
        for i in range(len(poly)):
            area += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1])
            j = i
        return abs(area) / 2.0
    raise ValueError(f"unknown shape {shape!r}; one of {SHAPES}")


_HEART_FRACTION: list[float] = []


def _heart_fraction(samples: int = 400) -> float:
    if not _HEART_FRACTION:
        hits = 0
        for i in range(samples):
            for j in range(samples):
                u = (i + 0.5) / samples * 2.0 - 1.0
                v = (j + 0.5) / samples * 2.0 - 1.0
                if _heart(u, v):
                    hits += 1
        _HEART_FRACTION.append(hits / (samples * samples))
    return _HEART_FRACTION[0]


def mask_grid(grid: Grid, keep: Callable[[float, float], bool]) -> Grid:
    """The grid with only the cells whose CENTRE passes `keep`. Row/col indices
    and the bounding width/height are unchanged (the frame stays the frame)."""
    cells = tuple(c for c in grid.cells if keep(c.x_mm, c.y_mm))
    if not cells:
        raise ValueError("shape leaves no cells at this size")
    return Grid(cap=grid.cap, width_mm=grid.width_mm,
                height_mm=grid.height_mm, cells=cells)
