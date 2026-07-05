"""Count-constrained stock assignment: which cap group fills which cell.

The photomosaic assignment problem with finite stock: given the desired CIELAB
colour of every cell and the owned cap groups (colour + how many you have),
pick a group for each cell so duplicates are spent well and scarce colours go
where they matter most. Greedy on the globally sorted (cell, group) ΔE00 pairs:
the best matches anywhere in the picture claim their stock first, and when
stock runs out the WORST-matching cells are the ones left unassigned (-1).

Pure numpy, deterministic. The ΔE00 matrix is a vectorised port of
``palette.ciede2000`` (verified against it in tests).
"""

from __future__ import annotations

import numpy as np


def ciede2000_matrix(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """Pairwise CIEDE2000: (N,3) x (M,3) -> (N,M). Mirrors palette.ciede2000."""
    l1, a1, b1 = (np.asarray(lab1, float)[:, None, i] for i in range(3))
    l2, a2, b2 = (np.asarray(lab2, float)[None, :, i] for i in range(3))

    avg_lp = (l1 + l2) / 2
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    avg_c = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(avg_c**7 / (avg_c**7 + 25.0**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    avg_cp = (c1p + c2p) / 2

    def hp(ap, bp):
        h = np.degrees(np.arctan2(bp, ap))
        return np.where((ap == 0) & (bp == 0), 0.0, np.where(h < 0, h + 360, h))

    h1p, h2p = hp(a1p, b1), hp(a2p, b2)

    dlp = l2 - l1
    dcp = c2p - c1p
    diff = h2p - h1p
    dhp = np.where(np.abs(diff) <= 180, diff,
                   np.where(diff > 180, diff - 360, diff + 360))
    dhp = np.where(c1p * c2p == 0, 0.0, dhp)
    dHp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) / 2)

    s = h1p + h2p
    avg_hp = np.where(c1p * c2p == 0, s,
                      np.where(np.abs(h1p - h2p) <= 180, s / 2,
                               np.where(s < 360, (s + 360) / 2, (s - 360) / 2)))

    t = (1 - 0.17 * np.cos(np.radians(avg_hp - 30))
         + 0.24 * np.cos(np.radians(2 * avg_hp))
         + 0.32 * np.cos(np.radians(3 * avg_hp + 6))
         - 0.20 * np.cos(np.radians(4 * avg_hp - 63)))
    sl = 1 + (0.015 * (avg_lp - 50) ** 2) / np.sqrt(20 + (avg_lp - 50) ** 2)
    sc = 1 + 0.045 * avg_cp
    sh = 1 + 0.015 * avg_cp * t
    d_theta = 30 * np.exp(-(((avg_hp - 275) / 25) ** 2))
    rc = 2 * np.sqrt(avg_cp**7 / (avg_cp**7 + 25.0**7))
    rt = -rc * np.sin(np.radians(2 * d_theta))

    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2
                   + rt * (dcp / sc) * (dHp / sh))


def assign_stock(
    cell_labs: np.ndarray,
    group_labs: np.ndarray,
    counts: np.ndarray,
) -> np.ndarray:
    """Assign each cell a group index (or -1 when the stock is exhausted)."""
    n = len(cell_labs)
    if n == 0:
        return np.zeros(0, dtype=int)
    d = ciede2000_matrix(cell_labs, group_labs)         # (N, G)
    order = np.argsort(d, axis=None, kind="stable")     # best pairs first, ties stable
    remaining = np.asarray(counts, dtype=int).copy()
    out = np.full(n, -1, dtype=int)
    filled = 0
    budget = int(remaining.sum())
    g_count = d.shape[1]
    for flat in order:
        cell, grp = divmod(int(flat), g_count)
        if out[cell] != -1 or remaining[grp] == 0:
            continue
        out[cell] = grp
        remaining[grp] -= 1
        filled += 1
        if filled == n or filled == budget:
            break
    return out
