import numpy as np

from cap_mosaic.core.dither import dither_grid
from cap_mosaic.core.palette import rgb_to_lab

BLACK_LAB = rgb_to_lab((0, 0, 0))
WHITE_LAB = rgb_to_lab((255, 255, 255))
BW = np.array([BLACK_LAB, WHITE_LAB])  # palette: index 0 = black, 1 = white
BW_L = np.array([0.0, 100.0])          # rough L of each for value comparisons


def _rgb_grid_to_lab(rgb_grid):
    h, w = rgb_grid.shape[:2]
    return np.array([[rgb_to_lab(tuple(int(v) for v in rgb_grid[y, x]))
                      for x in range(w)] for y in range(h)])


def _nearest(target_lab, palette_lab):
    """Plain per-cell nearest colour (no diffusion) for comparison."""
    d = ((target_lab[:, :, None, :] - palette_lab[None, None, :, :]) ** 2).sum(3)
    return d.argmin(2)


def test_uniform_midtone_uses_both_colours_not_one():
    # a flat 60%-grey field: nearest picks ONE colour everywhere; dither must mix
    grey = np.full((12, 12, 3), 153, np.uint8)
    lab = _rgb_grid_to_lab(grey)
    nearest = _nearest(lab, BW)
    dithered = dither_grid(lab, BW)
    assert len(np.unique(nearest)) == 1        # nearest is a solid block
    assert set(np.unique(dithered)) == {0, 1}  # dither uses both black and white


def test_dither_beats_nearest_on_area_average_error():
    # horizontal black->white gradient; compare block-averaged L to the target
    cols = np.linspace(0, 255, 24)
    rgb = np.repeat(np.tile(cols[None, :, None], (24, 1, 3)), 1, 0).astype(np.uint8)
    lab = _rgb_grid_to_lab(rgb)
    target_L = lab[:, :, 0]

    dith_L = BW_L[dither_grid(lab, BW)]
    near_L = BW_L[_nearest(lab, BW)]

    def block_mae(grid_L):
        blocks = grid_L.reshape(6, 4, 6, 4)          # 4x4 cell blocks
        tgt = target_L.reshape(6, 4, 6, 4).mean((1, 3))
        return np.abs(blocks.mean((1, 3)) - tgt).mean()

    assert block_mae(dith_L) < block_mae(near_L)


def test_holes_are_skipped_and_isolate_diffusion():
    grey = np.full((10, 10, 3), 153, np.uint8)
    lab = _rgb_grid_to_lab(grey)
    holes = np.zeros((10, 10), bool)
    holes[4:6, :] = True  # a horizontal band of holes splits the grid
    out = dither_grid(lab, BW, hole_mask=holes)
    assert np.all(out[holes] == -1)       # holes carry no cap
    assert np.all(out[~holes] >= 0)       # every other cell gets a colour
