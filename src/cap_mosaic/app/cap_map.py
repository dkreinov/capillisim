"""Printable cap map — a paint-by-numbers plan for placing caps by hand.

Each non-hole cell shows a short letter code for its colour on a swatch of that
colour; row/col rulers and a legend (letter -> swatch -> hex -> count) let you
work the board grid one cell at a time. Holes are left blank. Renders to a PIL
image; the web app saves it as PNG or PDF.
"""

from __future__ import annotations

import string
from collections import Counter

from PIL import Image, ImageDraw, ImageFont

from ..core.plan import GridPlan


def _label(i: int) -> str:
    """A, B, ... Z, AA, AB, ... for the i-th colour."""
    a = string.ascii_uppercase
    return a[i] if i < 26 else a[i // 26 - 1] + a[i % 26]


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("consola.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def _ink(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Readable text colour over `rgb` (black on light, white on dark)."""
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return (20, 20, 20) if lum > 140 else (240, 240, 240)


def cap_map_labels(plan: GridPlan) -> dict[tuple[int, int, int], str]:
    """Colour (rgb) -> letter code, ordered by descending cap count (BOM order)."""
    counts = Counter(tuple(c.rgb) for c in plan.cells if not c.is_hole)
    return {rgb: _label(i) for i, (rgb, _n) in enumerate(counts.most_common())}


def render_cap_map(plan: GridPlan, cell_px: int = 30) -> Image.Image:
    """Render the paint-by-numbers cap map for `plan` as an RGB image."""
    cells = [c for c in plan.cells if not c.is_hole]
    counts = Counter(tuple(c.rgb) for c in cells)
    labels = cap_map_labels(plan)
    names = {tuple(c.rgb): c.color_name for c in cells}

    rows = max((c.row for c in plan.cells), default=0) + 1
    cols = max((c.col for c in plan.cells), default=0) + 1
    ruler = cell_px  # left/top gutter for indices
    grid_w, grid_h = cols * cell_px, rows * cell_px
    legend_h = 26 * (len(labels) + 1) + 20
    W = ruler + grid_w + 20
    H = ruler + grid_h + legend_h + 20

    img = Image.new("RGB", (max(W, 240), max(H, 120)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    cell_font = _font(max(10, int(cell_px * 0.5)))
    small = _font(13)
    leg_font = _font(15)

    present = {(c.row, c.col): tuple(c.rgb) for c in cells}

    # column + row rulers (every 5)
    for col in range(cols):
        if col % 5 == 0:
            d.text((ruler + col * cell_px + 3, 6), str(col), font=small, fill=(90, 90, 90))
    for row in range(rows):
        if row % 5 == 0:
            d.text((4, ruler + row * cell_px + 6), str(row), font=small, fill=(90, 90, 90))

    # grid cells
    for row in range(rows):
        for col in range(cols):
            x, y = ruler + col * cell_px, ruler + row * cell_px
            rgb = present.get((row, col))
            if rgb is None:
                continue  # hole / absent -> blank
            d.rectangle([x, y, x + cell_px, y + cell_px], fill=rgb, outline=(170, 170, 170))
            lab = labels[rgb]
            tb = d.textbbox((0, 0), lab, font=cell_font)
            d.text((x + (cell_px - (tb[2] - tb[0])) / 2 - tb[0],
                    y + (cell_px - (tb[3] - tb[1])) / 2 - tb[1]),
                   lab, font=cell_font, fill=_ink(rgb))

    # legend
    ly = ruler + grid_h + 16
    d.text((ruler, ly), "Legend — letter · colour · count", font=leg_font, fill=(30, 30, 30))
    ly += 26
    for rgb, lab in labels.items():
        d.rectangle([ruler, ly, ruler + 20, ly + 20], fill=rgb, outline=(120, 120, 120))
        hexc = "#%02x%02x%02x" % rgb
        txt = f"{lab}   {hexc}   x{counts[rgb]}   {names.get(rgb, '')}".rstrip()
        d.text((ruler + 28, ly + 2), txt, font=leg_font, fill=(30, 30, 30))
        ly += 26
    return img
