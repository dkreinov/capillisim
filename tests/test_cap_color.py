import numpy as np

from cap_mosaic.app.cap_color import median_rgb, mosaic_rgb_from_crop


def _disc(n=96, field=(40, 80, 160)):
    """A crop-like image: coloured disc on white card background."""
    img = np.full((n, n, 3), 250, np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    mask = np.hypot(xx - n / 2, yy - n / 2) <= n / 2 - 2
    img[mask] = field
    return img, mask


def test_solid_cap_reads_its_own_colour():
    img, _ = _disc(field=(40, 80, 160))
    out = mosaic_rgb_from_crop(img)
    assert all(abs(a - b) <= 2 for a, b in zip(out, (40, 80, 160))), out


def test_mixing_is_linear_light_not_srgb():
    # cap face = fine 50/50 black/white checker; at distance it reads the LINEAR
    # midpoint (~188), not the sRGB average (~128)
    img, mask = _disc()
    n = img.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    checker = ((xx // 2 + yy // 2) % 2) == 0
    img[mask & checker] = 255
    img[mask & ~checker] = 0
    out = mosaic_rgb_from_crop(img)
    assert out[0] > 170, out  # linear mixing


def test_logo_mixes_into_the_distance_colour():
    # black field + central gold logo -> warmer and lighter than the field alone
    img, _ = _disc(field=(15, 12, 10))
    n = img.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    logo = np.hypot(xx - n / 2, yy - n / 2) <= n * 0.22
    img[logo] = (212, 175, 55)  # gold
    plain = mosaic_rgb_from_crop(_disc(field=(15, 12, 10))[0])
    out = mosaic_rgb_from_crop(img)
    assert out[0] > plain[0] + 15  # lighter
    assert out[0] > out[2] + 10  # warm (gold pulled R above B)


def test_minority_glare_is_excluded():
    # a thin specular streak of pure white must not lift the colour
    img, _ = _disc(field=(60, 60, 60))
    with_glare = img.copy()
    n = img.shape[0]
    with_glare[n // 2 - 2:n // 2 + 2, n // 4:3 * n // 4] = 255
    a = mosaic_rgb_from_crop(img)
    b = mosaic_rgb_from_crop(with_glare)
    assert abs(a[0] - b[0]) <= 6, (a, b)  # streak dropped, colour stable


def test_card_crop_with_small_cap_ignores_the_white_surround():
    # real crops are CARD-circle crops: the cap is a smaller disc inside them,
    # surrounded by white card. A dark cap must NOT read light-gray.
    n = 128
    img = np.full((n, n, 3), 250, np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    cap = np.hypot(xx - n * 0.45, yy - n * 0.52) <= n * 0.30  # off-centre, small
    img[cap] = (18, 15, 12)
    out = mosaic_rgb_from_crop(img)
    assert out[0] < 60, out  # dark cap stays dark; white card excluded


def test_median_rgb_is_per_channel_and_robust():
    colors = [(10, 20, 30), (12, 22, 32), (200, 200, 200)]  # one bad frame
    assert median_rgb(colors) == (12, 22, 32)
