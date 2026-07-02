"""Mosaic colour of a cap: what it contributes to the picture at viewing distance.

A cap is not one flat colour — field + logo + rim mix optically when the cap
subtends a few arcminutes. The physically correct single colour is the
**linear-light area mean** of the cap face (the same optics as
``planner_designer.view_at_distance``): sRGB -> linear, average, -> sRGB.
Minority specular glare is excluded first so a highlight streak can't lift it.

This is distinct from the *field* colour (``vision.card_reader.read_cap_field``),
which isolates the dominant cluster for recognising a cap in hand. Store both:
mosaic colour for planning/matching, field colour for recognition.
"""

from __future__ import annotations

import numpy as np

from ..core.palette import RGB

GLARE_LEVEL = 240  # all-channel brightness above this is treated as specular glare


def _srgb_to_linear(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def mosaic_rgb_from_crop(
    crop_rgb: np.ndarray, disc_frac: float = 0.94, glare_level: int = GLARE_LEVEL
) -> RGB:
    """Linear-light mean colour of the cap disc in a square crop (RGB array).

    Masks to the centre disc (``disc_frac`` of the half-width, skipping the card
    background at the corners), drops minority glare pixels, then averages in
    linear light. A mostly-bright cap (white/silver) keeps its pixels — masking
    a majority would leave only its shadows.
    """
    a = np.asarray(crop_rgb, dtype=np.uint8)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    disc = np.hypot(xx - w / 2.0, yy - h / 2.0) <= (min(h, w) / 2.0) * disc_frac
    px = a[disc].reshape(-1, 3)
    if px.size == 0:
        px = a.reshape(-1, 3)
    # Specular glare is a SMALL bright patch; drop it only when it's a clear
    # minority (<25%). A white cap — or a bright pattern — is really that bright.
    not_glare = ~np.all(px > glare_level, axis=1)
    if not_glare.mean() >= 0.75:
        px = px[not_glare]
    lin = _srgb_to_linear(px.astype(np.float64) / 255.0)
    mean = _linear_to_srgb(lin.mean(axis=0))
    return tuple(int(round(v * 255)) for v in np.clip(mean, 0.0, 1.0))


def median_rgb(colors: list[RGB]) -> RGB:
    """Per-channel median of several colour readings (robust to one bad frame)."""
    arr = np.asarray(colors, dtype=float)
    med = np.median(arr, axis=0)
    return tuple(int(round(v)) for v in med)
