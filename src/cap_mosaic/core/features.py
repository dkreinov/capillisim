"""Thin-feature detection + thickening for cap mosaics.

Bottle caps are one large "pixel" each, so a 1-cap-wide line (an eye, a mouth,
a skyline edge, a black-hole ring) tends to vanish at viewing distance. This
module works on the low-resolution **cap grid** (an ``(rows, cols, 3)`` RGB
array, one cell per cap): it flags dark strokes that are only ~1 cap thick and
can widen them to at least 2 caps so important outlines survive.

Pure numpy — no I/O, no scipy. 4-neighbour morphology via array shifts.
"""

from __future__ import annotations

import numpy as np

DARK_MAX = 90  # luma at/below this counts as a dark (ink/outline) cell


def luminance(grid_rgb: np.ndarray) -> np.ndarray:
    a = np.asarray(grid_rgb, dtype=np.float64)
    return a[..., :3] @ np.array([0.299, 0.587, 0.114])


def _dilate(mask: np.ndarray) -> np.ndarray:
    """Grow a boolean mask by one cell in the 4-neighbourhood."""
    out = mask.copy()
    out[:-1] |= mask[1:]
    out[1:] |= mask[:-1]
    out[:, :-1] |= mask[:, 1:]
    out[:, 1:] |= mask[:, :-1]
    return out


def _erode(mask: np.ndarray) -> np.ndarray:
    return ~_dilate(~mask)


def thin_dark_mask(grid_rgb: np.ndarray, dark_max: int = DARK_MAX) -> np.ndarray:
    """Dark cells that belong to a stroke only ~1 cap wide.

    A morphological opening (erode then dilate) removes strokes that are too thin
    to survive erosion; whatever the opening deletes was a thin feature.
    """
    dark = luminance(grid_rgb) <= dark_max
    opened = _dilate(_erode(dark))
    return dark & ~opened


def count_thin_features(grid_rgb: np.ndarray, dark_max: int = DARK_MAX) -> int:
    """How many cap cells sit on a ~1-cap-thin dark stroke."""
    return int(thin_dark_mask(grid_rgb, dark_max).sum())


def thicken_dark_lines(grid_rgb: np.ndarray, dark_max: int = DARK_MAX) -> np.ndarray:
    """Widen ~1-cap-thin dark strokes to 2 caps so they don't disappear.

    Each light cell adjacent to a thin stroke is recoloured with the colour of a
    neighbouring dark cell. Solid dark blocks are left alone. Returns a new grid.
    """
    grid = np.array(grid_rgb, copy=True)
    dark = luminance(grid) <= dark_max
    thin = thin_dark_mask(grid, dark_max)
    if not thin.any():
        return grid
    grow = _dilate(thin) & ~dark  # light neighbours of thin strokes
    rows, cols = grow.shape
    for r, c in zip(*np.where(grow)):
        # copy the colour of the first dark 4-neighbour (the stroke it extends)
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and dark[nr, nc]:
                grid[r, c] = grid[nr, nc]
                break
    return grid
