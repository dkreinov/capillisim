"""Procedurally generated cap images for realistic mosaic simulation.

Rendering a mosaic from flat colour disks looks nothing like real caps. These
synthetic caps have a coloured field, a darker crimped rim, and a random marking
(letters / ring / bars) in a contrasting colour — so the "up close you see caps,
far away you see the picture" simulation actually reads like caps. Deterministic
per seed. Use these to fill palette colours the real ``caps.db`` doesn't cover.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from ..core.palette import RGB

_MARKINGS = ("text", "ring", "bars")
_LETTERS = "ABCDEFGHKMNPRSTVXZ"


@dataclass
class CapImage:
    rgb: RGB
    image: Image.Image  # RGBA, square, a circular cap on a transparent field


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def _lum(c: RGB) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _contrast(c: RGB) -> RGB:
    return (20, 20, 20) if _lum(c) > 140 else (235, 235, 235)


def render_fake_cap(rgb: RGB, size: int = 64, seed: int = 0, markings: bool = True) -> CapImage:
    """Draw one synthetic cap of base colour `rgb` as an RGBA image."""
    rng = random.Random(seed)
    rgb = tuple(int(v) for v in rgb)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size / 2.0
    r = m - 1
    d.ellipse([m - r, m - r, m + r, m + r], fill=(*rgb, 255))
    rim = tuple(int(v * 0.55) for v in rgb)
    d.ellipse([m - r, m - r, m + r, m + r], outline=(*rim, 255), width=max(2, size // 14))

    if markings:
        fg = (*_contrast(rgb), 255)
        kind = _MARKINGS[rng.randrange(len(_MARKINGS))]
        if kind == "text":
            txt = "".join(rng.choice(_LETTERS) for _ in range(rng.randint(1, 2)))
            font = _font(int(size * 0.45))
            box = d.textbbox((0, 0), txt, font=font)
            d.text(
                (m - (box[2] - box[0]) / 2 - box[0], m - (box[3] - box[1]) / 2 - box[1]),
                txt, font=font, fill=fg,
            )
        elif kind == "ring":
            rr = r * 0.5
            d.ellipse([m - rr, m - rr, m + rr, m + rr], outline=fg, width=max(2, size // 12))
        else:  # bars
            for k in (-1, 0, 1):
                y = m + k * r * 0.35
                d.line([m - r * 0.5, y, m + r * 0.5, y], fill=fg, width=max(1, size // 18))
    return CapImage(rgb, img)


def fake_cap_library(
    colors: list[RGB], size: int = 64, seed: int = 0, markings: bool = True
) -> list[CapImage]:
    """One synthetic cap per colour (deterministic for a given seed)."""
    return [
        render_fake_cap(c, size=size, seed=seed + i, markings=markings)
        for i, c in enumerate(colors)
    ]
