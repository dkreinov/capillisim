"""Card reader -> matcher: needed cap accepts to the right cell; unneeded rejects."""

import numpy as np
from PIL import ImageDraw

from cap_mosaic.app.card_build import process_frame
from cap_mosaic.app.make_card import render_card
from cap_mosaic.core.matcher import Matcher
from cap_mosaic.core.plan import GridPlan, PlannedCell
from cap_mosaic.vision import card_layout as L
from cap_mosaic.vision.card_reader import CardCapReader


def _plan():
    cells = [
        PlannedCell(0, 0, 10.0, 10.0, "red", (190, 40, 45)),
        PlannedCell(0, 1, 40.0, 10.0, "blue", (40, 80, 160)),
    ]
    return GridPlan(cap_diameter_mm=32.0, width_mm=80.0, height_mm=40.0, cells=cells)


def _frame_with_cap(true_rgb, dpi=200):
    ppm = dpi / 25.4
    card = render_card(dpi).copy()
    draw = ImageDraw.Draw(card)
    cx, cy = L.CIRCLE_CX_MM * ppm, L.CIRCLE_CY_MM * ppm
    r = L.CIRCLE_R_MM * ppm * 0.85
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=true_rgb)
    return np.clip(np.asarray(card).astype(np.float32) * np.array([0.9, 0.8, 0.7]), 0, 255).astype(np.uint8)


def test_needed_cap_accepts_to_correct_cell():
    matcher = Matcher(_plan(), reject_threshold=15.0)
    res = process_frame(_frame_with_cap((200, 60, 55)), CardCapReader(), matcher)
    assert res.state == "accept"
    assert res.cell is not None and res.cell.color_name == "red"


def test_unneeded_cap_rejects():
    matcher = Matcher(_plan(), reject_threshold=15.0)
    res = process_frame(_frame_with_cap((50, 140, 80)), CardCapReader(), matcher)  # green
    assert res.state == "reject"
