import numpy as np

from cap_mosaic.core import features


def _grid_with_thin_cross(n=11, dark=(20, 20, 20), light=(230, 230, 230)):
    """Light field with a 1-cell-wide dark cross (thin lines)."""
    g = np.full((n, n, 3), light, np.uint8)
    mid = n // 2
    g[mid, :] = dark
    g[:, mid] = dark
    return g


def _grid_with_thick_block(n=11, dark=(20, 20, 20), light=(230, 230, 230)):
    """Light field with a solid 4x4 dark block (not thin)."""
    g = np.full((n, n, 3), light, np.uint8)
    g[3:7, 3:7] = dark
    return g


def test_detects_thin_lines():
    n = 11
    thin = features.thin_dark_mask(_grid_with_thin_cross(n))
    # most of the 1-cell cross is flagged thin (the intersection reads as 2D and
    # legitimately survives erosion, so a few central cells aren't flagged)
    assert thin.sum() >= 12


def test_does_not_flag_thick_blocks_as_thin():
    thin = features.thin_dark_mask(_grid_with_thick_block())
    # a solid 4x4 block has a surviving core -> few/none flagged thin
    assert thin.sum() <= 4


def test_count_thin_features_zero_on_flat_image():
    flat = np.full((10, 10, 3), (128, 128, 128), np.uint8)
    assert features.count_thin_features(flat) == 0


def test_thicken_widens_thin_lines():
    g = _grid_with_thin_cross(11)
    before_dark = (features.luminance(g) <= 90).sum()
    out = features.thicken_dark_lines(g)
    after_dark = (features.luminance(out) <= 90).sum()
    assert after_dark > before_dark  # lines grew
    # after thickening, the lines are no longer 1-cell thin
    assert features.count_thin_features(out) < features.count_thin_features(g)


def test_thicken_preserves_shape_and_leaves_flat_image_untouched():
    flat = np.full((8, 8, 3), (200, 200, 200), np.uint8)
    out = features.thicken_dark_lines(flat)
    assert out.shape == flat.shape
    assert np.array_equal(out, flat)  # nothing dark to thicken
