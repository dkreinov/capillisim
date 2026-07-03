"""Heuristic 'is this a good cap-art image?' judge.

Cap art reads best with BOLD shapes, HIGH contrast, a strong subject against a
SIMPLE background, and not-too-fine detail (each cap is one fat pixel). This
scores an image on those axes (0-100), gives a verdict, concrete tips, and
recommended settings (minimum size, dither/thicken, a palette preset guess).

Deterministic — no LLM. Pure numpy + reuses `core.legibility` for the detail
estimate, so it runs and tests headless.
"""

from __future__ import annotations

import numpy as np

from .legibility import min_caps_across

_GRAY = np.array([0.299, 0.587, 0.114])


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _preset_guess(mean_rgb: np.ndarray, brightness: float, sat: float) -> str:
    """Best-effort palette preset from overall colour feel (a hint, not a rule)."""
    r, g, b = mean_rgb
    warm = r > b + 20
    if brightness < 95 and sat > 30:
        return "space"          # dark + colourful -> nebula/space ramp
    if warm and brightness > 120:
        return "sunset"         # warm & bright -> sunset bands
    if warm and 70 < brightness < 175 and sat < 70:
        return "portrait"       # muted warm mid-tones -> skin ramp
    return ""                    # auto (derive from image)


def critique(image_rgb, mode: str = "picture", pitch_mm: float = 32.0) -> dict:
    """Score `image_rgb` for cap-art suitability and recommend settings."""
    a = np.asarray(image_rgb)[..., :3].astype(np.uint8)
    h, w = a.shape[:2]
    aspect = w / h
    gray = a @ _GRAY

    contrast = float(np.std(gray))                       # ~0..128
    floor = min_caps_across(a, mode=mode, aspect=aspect)  # detail: caps-across to read

    # background simplicity: how uniform the outer border ring is (clean = pops)
    b = max(2, min(h, w) // 20)
    border = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3),
                             a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    bg_spread = float(np.mean(np.std(border, axis=0)))    # low = clean background

    mean_rgb = a.reshape(-1, 3).mean(0)
    brightness = float(mean_rgb.mean())
    sat = float(np.mean(a.max(2).astype(int) - a.min(2)))  # crude saturation

    s_contrast = _clamp01(contrast / 60.0)
    s_bold = _clamp01((100 - floor) / (100 - 8))          # low floor = bold = good
    s_bg = _clamp01(1 - bg_spread / 60.0)
    score = round(100 * (0.4 * s_contrast + 0.4 * s_bold + 0.2 * s_bg))

    verdict = ("great" if score >= 75 else "good" if score >= 55
               else "tricky" if score >= 35 else "poor")

    tips: list[str] = []
    if s_contrast < 0.5:
        tips.append("Low contrast — boost contrast or choose a bolder subject; "
                    "cap art is a shouting medium.")
    else:
        tips.append("Good contrast — the subject will pop as caps.")
    if floor >= 60:
        tips.append(f"Very detailed — needs ~{floor} caps across; go large "
                    f"(≥{floor * pitch_mm / 1000:.1f} m wide) or simplify the image.")
    elif floor <= 24:
        tips.append("Bold and simple — reads even at a small size.")
    if s_bg < 0.5:
        tips.append("Busy background — crop to the subject (or it competes with it).")

    recommend = {
        "min_size_m": round(floor * pitch_mm / 1000.0, 2),
        "dither": True,                       # smooths tones in a small palette
        "thicken": floor >= 40,               # protect thin strokes on detailed art
        "preset": _preset_guess(mean_rgb, brightness, sat),
    }
    return {
        "score": score,
        "verdict": verdict,
        "tips": tips,
        "recommend": recommend,
        "signals": {"contrast": round(contrast, 1), "detail_floor": floor,
                    "bg_spread": round(bg_spread, 1)},
    }
