import numpy as np

from cap_mosaic.core.assign import assign_stock, ciede2000_matrix
from cap_mosaic.core.palette import ciede2000, rgb_to_lab


def _lab(*rgbs):
    return np.array([rgb_to_lab(c) for c in rgbs])


def test_matrix_matches_scalar_ciede2000():
    rng = np.random.default_rng(3)
    a = rng.integers(0, 256, (5, 3))
    b = rng.integers(0, 256, (4, 3))
    la, lb = _lab(*map(tuple, a)), _lab(*map(tuple, b))
    m = ciede2000_matrix(la, lb)
    for i in range(5):
        for j in range(4):
            assert abs(m[i, j] - ciede2000(tuple(la[i]), tuple(lb[j]))) < 1e-6


def test_scarce_colour_lands_on_its_best_cell():
    cells = _lab((200, 30, 30), (205, 25, 28), (128, 128, 128), (120, 120, 120))
    groups = _lab((202, 28, 29), (125, 125, 125))     # one red, one grey
    counts = np.array([1, 3])                          # red is scarce
    out = assign_stock(cells, groups, counts)
    assert (out[:2] == 0).sum() == 1                   # red used exactly once, on a red cell
    assert (out == 1).sum() == 3                       # grey fills the rest
    assert (out >= 0).all()                            # nothing unassigned (4 cells, 4 caps)


def test_counts_respected_and_worst_cells_sacrificed():
    # 3 cells, stock of 2: the OFF-colour cell is the one left unassigned
    cells = _lab((10, 10, 10), (12, 12, 12), (250, 250, 0))  # two dark, one yellow
    groups = _lab((11, 11, 11))
    counts = np.array([2])
    out = assign_stock(cells, groups, counts)
    assert (out == 0).sum() == 2
    assert out[2] == -1                                # the yellow cell loses


def test_deterministic():
    rng = np.random.default_rng(7)
    cells = _lab(*[tuple(c) for c in rng.integers(0, 256, (30, 3))])
    groups = _lab(*[tuple(c) for c in rng.integers(0, 256, (5, 3))])
    counts = np.array([6, 6, 6, 6, 6])
    a = assign_stock(cells, groups, counts)
    b = assign_stock(cells, groups, counts)
    assert (a == b).all()
