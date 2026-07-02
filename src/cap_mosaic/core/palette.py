"""Color handling: sRGB <-> CIELAB, CIEDE2000 distance, and palette binning.

Caps come in a limited set of colors, so building a mosaic is a color
quantization problem against an achievable palette. We compare colors
perceptually (CIEDE2000 in CIELAB) rather than in raw RGB, which matches the eye
far better and keeps near-duplicate caps from being treated as very different.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RGB = tuple[int, int, int]
Lab = tuple[float, float, float]


@dataclass(frozen=True)
class CapColor:
    name: str
    rgb: RGB

    @property
    def lab(self) -> Lab:
        return rgb_to_lab(self.rgb)


# A pragmatic starting palette for beer caps. Metallic finishes (silver/gold)
# are approximated by a representative mid-tone; the vision layer will refine
# these against real photographed caps later.
DEFAULT_PALETTE: tuple[CapColor, ...] = (
    CapColor("white", (245, 245, 245)),
    CapColor("silver", (170, 172, 175)),
    CapColor("black", (28, 28, 28)),
    CapColor("red", (190, 40, 45)),
    CapColor("green", (40, 120, 70)),
    CapColor("blue", (40, 80, 160)),
    CapColor("gold", (190, 150, 70)),
    CapColor("yellow", (225, 200, 70)),
    CapColor("orange", (220, 120, 45)),
    CapColor("brown", (110, 75, 55)),
)


# Curated small palettes for cap art. A tight, purpose-built palette reads far
# better than many auto-clustered shades — "limited palette makes it powerful".
# Subject-specific tone families (portrait skin ramp, sunset bands, space).
PORTRAIT_PALETTE: tuple[CapColor, ...] = (
    CapColor("outline", (25, 22, 20)),      # hair / dark outline
    CapColor("deepshadow", (60, 40, 32)),   # deep shadow
    CapColor("shadow", (110, 72, 55)),      # mid shadow
    CapColor("skin", (188, 132, 98)),       # skin midtone
    CapColor("highlight", (236, 206, 176)), # highlight
    CapColor("backdrop", (62, 72, 92)),     # cool background
)

SUNSET_PALETTE: tuple[CapColor, ...] = (
    CapColor("night", (32, 26, 62)),        # dark blue / purple sky
    CapColor("purple", (98, 46, 112)),
    CapColor("red", (202, 56, 60)),
    CapColor("orange", (230, 120, 50)),
    CapColor("yellow", (240, 205, 92)),
    CapColor("sun", (250, 244, 220)),
    CapColor("sea", (20, 30, 42)),          # dark sea / ground
)

SPACE_PALETTE: tuple[CapColor, ...] = (
    CapColor("void", (12, 12, 18)),         # black background
    CapColor("deepblue", (26, 36, 72)),
    CapColor("nebula", (82, 50, 112)),      # purple nebula
    CapColor("star", (226, 228, 236)),      # silver/white stars
    CapColor("ring", (236, 176, 72)),       # accretion-ring gold
    CapColor("flare", (220, 110, 46)),      # orange
    CapColor("ember", (172, 52, 56)),       # red
)

PRESETS: dict[str, tuple[CapColor, ...]] = {
    "default": DEFAULT_PALETTE,
    "portrait": PORTRAIT_PALETTE,
    "sunset": SUNSET_PALETTE,
    "space": SPACE_PALETTE,
}


def preset_palette(name: str) -> tuple[CapColor, ...] | None:
    """A curated palette by name (portrait/sunset/space/default), or None."""
    return PRESETS.get((name or "").strip().lower())


def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb: RGB) -> Lab:
    r, g, b = (_srgb_to_linear(v) for v in rgb)
    # linear sRGB -> XYZ (D65)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    # normalize by D65 white
    x, y, z = x / 0.95047, y / 1.0, z / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(lab1: Lab, lab2: Lab) -> float:
    """Perceptual color difference (CIEDE2000). Smaller is more similar."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    avg_lp = (l1 + l2) / 2
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    avg_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(avg_c**7 / (avg_c**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    avg_cp = (c1p + c2p) / 2

    def hp(ap: float, bp: float) -> float:
        if ap == 0 and bp == 0:
            return 0.0
        h = math.degrees(math.atan2(bp, ap))
        return h + 360 if h < 0 else h

    h1p, h2p = hp(a1p, b1), hp(a2p, b2)

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)

    if c1p * c2p == 0:
        avg_hp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        avg_hp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        avg_hp = (h1p + h2p + 360) / 2
    else:
        avg_hp = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(avg_hp - 30))
        + 0.24 * math.cos(math.radians(2 * avg_hp))
        + 0.32 * math.cos(math.radians(3 * avg_hp + 6))
        - 0.20 * math.cos(math.radians(4 * avg_hp - 63))
    )
    sl = 1 + (0.015 * (avg_lp - 50) ** 2) / math.sqrt(20 + (avg_lp - 50) ** 2)
    sc = 1 + 0.045 * avg_cp
    sh = 1 + 0.015 * avg_cp * t
    d_theta = 30 * math.exp(-(((avg_hp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(avg_cp**7 / (avg_cp**7 + 25**7))
    rt = -rc * math.sin(math.radians(2 * d_theta))

    return math.sqrt(
        (dlp / sl) ** 2
        + (dcp / sc) ** 2
        + (dHp / sh) ** 2
        + rt * (dcp / sc) * (dHp / sh)
    )


def nearest(rgb: RGB, palette: tuple[CapColor, ...] = DEFAULT_PALETTE) -> CapColor:
    """Return the palette cap color perceptually closest to `rgb`."""
    target = rgb_to_lab(rgb)
    return min(palette, key=lambda c: ciede2000(target, c.lab))


def distance(rgb: RGB, cap: CapColor) -> float:
    """Perceptual distance from an arbitrary color to a palette cap color."""
    return ciede2000(rgb_to_lab(rgb), cap.lab)
