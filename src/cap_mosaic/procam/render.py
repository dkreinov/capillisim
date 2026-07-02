"""Render the projector frame.

Given a plan and a calibration, produce the image the projector should display:
an optional faint template of every cell at its true table position, plus a
bright glowing highlight on the single cell where the next cap should go. The
frame is built in projector-pixel space via the calibration homography, so what
lands on the table is at correct 1:1 scale.

This module is pure (returns a PIL image) so it is testable headless. Putting
the frame fullscreen on the projector is a thin display step done on the real
rig (see display_fullscreen).
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..core.plan import GridPlan, PlannedCell
from .calibrate import Calibration

BLACK = (0, 0, 0)
TEMPLATE_RING = (40, 40, 40)
FILLED_RING = (90, 90, 90)
HIGHLIGHT = (60, 255, 90)


def render_projection(
    plan: GridPlan,
    cal: Calibration,
    highlight: PlannedCell | None = None,
    show_template: bool = True,
    show_filled: bool = True,
) -> Image.Image:
    """Build the projector image for the current build state."""
    img = Image.new("RGB", (cal.proj_width, cal.proj_height), BLACK)
    draw = ImageDraw.Draw(img)
    r_mm = plan.cap_diameter_mm / 2.0

    if show_template:
        for cell in plan.cells:
            if cell.filled and not show_filled:
                continue
            color = FILLED_RING if cell.filled else TEMPLATE_RING
            _ring(draw, cal, cell, r_mm, color, width=2)

    if highlight is not None:
        _glow(draw, cal, highlight, r_mm)

    return img


def render_mosaic_projection(
    plan: GridPlan,
    cal: Calibration,
    highlight: PlannedCell | None = None,
) -> Image.Image:
    """Project the *image being built*: every cell filled with its target cap
    colour (so the picture is visible), placed cells ringed white, and a glow on
    the next target cell.
    """
    img = Image.new("RGB", (cal.proj_width, cal.proj_height), BLACK)
    draw = ImageDraw.Draw(img)
    r_mm = plan.cap_diameter_mm / 2.0
    for cell in plan.cells:
        cx, cy = cal.table_mm_to_proj_px(cell.x_mm, cell.y_mm)
        r = cal.mm_radius_to_px(cell.x_mm, cell.y_mm, r_mm)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(cell.rgb))
        if cell.filled:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=2)
    if highlight is not None:
        _glow(draw, cal, highlight, r_mm)
    return img


def render_stencil(
    plan: GridPlan,
    cal: Calibration,
    color: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Project the whole plan as a colour stencil at 1:1 on the table.

    Every non-hole cell is filled with its cap colour, so you drop each cap onto
    the disc that lights up in its colour. With ``color`` (an rgb tuple) only that
    colour's cells are lit — the per-colour glue pass: fill all of one colour,
    then move to the next. Holes are never lit; already-placed cells get a white
    ring for progress. Pure (returns a PIL image), so it tests headless.
    """
    img = Image.new("RGB", (cal.proj_width, cal.proj_height), BLACK)
    draw = ImageDraw.Draw(img)
    r_mm = plan.cap_diameter_mm / 2.0
    key = tuple(color) if color is not None else None
    for cell in plan.cells:
        if cell.is_hole:
            continue  # a deliberate empty cell is never lit
        if key is not None and tuple(cell.rgb) != key:
            continue  # per-colour pass: only the chosen colour
        cx, cy = cal.table_mm_to_proj_px(cell.x_mm, cell.y_mm)
        r = cal.mm_radius_to_px(cell.x_mm, cell.y_mm, r_mm)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(cell.rgb))
        if cell.filled:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=2)
    return img


def _ring(draw, cal, cell, r_mm, color, width):
    cx, cy = cal.table_mm_to_proj_px(cell.x_mm, cell.y_mm)
    r = cal.mm_radius_to_px(cell.x_mm, cell.y_mm, r_mm)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)


def _glow(draw, cal, cell, r_mm):
    """A bright target: concentric rings fading outward to read as a glow."""
    cx, cy = cal.table_mm_to_proj_px(cell.x_mm, cell.y_mm)
    r = cal.mm_radius_to_px(cell.x_mm, cell.y_mm, r_mm)
    for k, scale in enumerate((1.6, 1.3, 1.0)):
        shade = 60 + 65 * k
        col = (int(0.2 * shade), shade, int(0.35 * shade))
        rr = r * scale
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=3)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=HIGHLIGHT, width=4)


def display_fullscreen(
    img: Image.Image, monitor_x: int = 0, hold_ms: int = 0
) -> None:  # pragma: no cover - needs a display
    """Show `img` fullscreen on the projector once (real-rig only).

    A one-shot convenience (e.g. for calibration test patterns). For the live
    build loop, hold a single :class:`cap_mosaic.procam.display.Projector` open
    and call ``show`` per frame instead of recreating the window each time.
    ``hold_ms=0`` blocks until a key is pressed.
    """
    from .display import Projector  # noqa: PLC0415

    proj = Projector(monitor_x=monitor_x)
    proj.show(img, 1)
    proj.wait_key(hold_ms)
    proj.close()
