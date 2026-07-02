"""Error-diffusion dithering on the cap grid, in CIELAB.

With only a handful of cap colours, per-cell nearest-colour quantization bands
badly. Floyd–Steinberg error diffusion spreads each cell's quantization error to
its not-yet-visited neighbours (serpentine order), so the *area-average* of the
placed caps matches the target — the eye blends them at viewing distance. Errors
are measured and diffused in CIELAB (perceptually even). Holes are skipped: no
error flows into or out of a deliberate empty cell.

Pure numpy — no I/O.
"""

from __future__ import annotations

import numpy as np

# Floyd–Steinberg kernel as (dy, dx, weight/16). dx is mirrored on right-to-left
# (serpentine) rows so the diffusion stays ahead of the scan.
_FS = ((0, 1, 7), (1, -1, 3), (1, 0, 5), (1, 1, 1))


def dither_grid(
    target_lab: np.ndarray,
    palette_lab: np.ndarray,
    hole_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Serpentine Floyd–Steinberg dithering of `target_lab` onto `palette_lab`.

    - ``target_lab``: ``(H, W, 3)`` desired CIELAB colour per cell.
    - ``palette_lab``: ``(K, 3)`` available cap colours in CIELAB.
    - ``hole_mask``: optional ``(H, W)`` bool; True cells are holes (skipped, and
      no error is diffused into them).

    Returns an ``(H, W)`` int array of palette indices, ``-1`` for holes.
    """
    work = np.array(target_lab, dtype=float)  # mutated with diffused error
    palette = np.asarray(palette_lab, dtype=float)
    h, w = work.shape[:2]
    holes = (np.zeros((h, w), bool) if hole_mask is None
             else np.asarray(hole_mask, bool))
    out = np.full((h, w), -1, dtype=int)

    for y in range(h):
        rightward = y % 2 == 0
        xs = range(w) if rightward else range(w - 1, -1, -1)
        d = 1 if rightward else -1  # travel direction; mirrors the FS x-offsets
        for x in xs:
            if holes[y, x]:
                continue
            old = work[y, x]
            k = int(np.argmin(((palette - old) ** 2).sum(1)))
            out[y, x] = k
            err = old - palette[k]
            for dy, dx, wt in _FS:
                ny, nx = y + dy, x + dx * d
                if 0 <= ny < h and 0 <= nx < w and not holes[ny, nx]:
                    work[ny, nx] += err * (wt / 16.0)
    return out
