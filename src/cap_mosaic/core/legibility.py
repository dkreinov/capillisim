"""Legibility floor: the minimum caps-across for an image to still read.

A mosaic made of caps is a heavy downsampling of the target image. Below some
number of caps the subject simply can't be represented — and then *no* viewing
distance recovers it. We estimate that floor content-aware: render the image at N
caps-across, compare its structure to the original (windowed SSIM), and take the
smallest N whose similarity clears a threshold. A detailed scene needs many more
caps than a simple/flat one; "pattern" mode (no subject to recognise) uses a
looser threshold.

Pure numpy — no I/O, no PIL. Callers pass an (H, W, 3) uint8/float RGB array.
"""

from __future__ import annotations

import numpy as np

# SSIM the reduced image must reach to count as "reads". Tunable; the web app
# exposes it so it can be calibrated against real images.
PICTURE_THRESHOLD = 0.75
PATTERN_THRESHOLD = 0.55
CANDIDATES = (6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64, 80, 100)
_WORK = 200  # long-side working resolution (keeps it fast on big uploads)


def _to_gray(rgb: np.ndarray) -> np.ndarray:
    a = np.asarray(rgb, dtype=np.float64)
    if a.ndim == 3:
        a = a[..., :3] @ np.array([0.299, 0.587, 0.114])
    return a


def _resize_nearest(a: np.ndarray, nh: int, nw: int) -> np.ndarray:
    h, w = a.shape
    yi = np.linspace(0, h - 1, nh).round().astype(int)
    xi = np.linspace(0, w - 1, nw).round().astype(int)
    return a[yi][:, xi]


def _downsample_mean(gray: np.ndarray, nx: int, ny: int) -> np.ndarray:
    """Area-average `gray` down to ny x nx bins (vectorised, via an integral image)."""
    h, w = gray.shape
    nx = max(1, min(nx, w))
    ny = max(1, min(ny, h))
    xe = np.linspace(0, w, nx + 1).astype(int)
    ye = np.linspace(0, h, ny + 1).astype(int)
    cs = np.zeros((h + 1, w + 1))
    cs[1:, 1:] = gray.cumsum(0).cumsum(1)
    y0, y1, x0, x1 = ye[:-1], ye[1:], xe[:-1], xe[1:]
    block = cs[y1][:, x1] - cs[y0][:, x1] - cs[y1][:, x0] + cs[y0][:, x0]
    counts = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    return block / counts


def _box_mean(a: np.ndarray, k: int) -> np.ndarray:
    """Mean over k x k windows (edge-padded, same shape) via an integral image."""
    pad = k // 2
    ap = np.pad(a, pad, mode="edge")
    cs = ap.cumsum(0).cumsum(1)
    cs = np.pad(cs, ((1, 0), (1, 0)))
    h, w = a.shape
    s = cs[k:k + h, k:k + w] - cs[:h, k:k + w] - cs[k:k + h, :w] + cs[:h, :w]
    return s / (k * k)


def _ssim(a: np.ndarray, b: np.ndarray, k: int = 7) -> float:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    mu_a, mu_b = _box_mean(a, k), _box_mean(b, k)
    va = _box_mean(a * a, k) - mu_a**2
    vb = _box_mean(b * b, k) - mu_b**2
    cov = _box_mean(a * b, k) - mu_a * mu_b
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / (
        (mu_a**2 + mu_b**2 + c1) * (va + vb + c2)
    )
    return float(np.clip(s, -1.0, 1.0).mean())


def _prep(rgb: np.ndarray) -> np.ndarray:
    """Grayscale, downscaled once to the working resolution."""
    gray = _to_gray(rgb)
    h, w = gray.shape
    if max(h, w) > _WORK:
        scale = _WORK / max(h, w)
        gray = _resize_nearest(gray, max(1, round(h * scale)), max(1, round(w * scale)))
    return gray


def _score_gray(gray: np.ndarray, caps_across: int, aspect: float) -> float:
    h, w = gray.shape
    ny = max(1, round(caps_across / aspect))
    up = _resize_nearest(_downsample_mean(gray, caps_across, ny), h, w)
    return _ssim(gray, up)


def legibility_score(rgb: np.ndarray, caps_across: int, aspect: float) -> float:
    """Structural similarity of the image rendered at `caps_across` vs the original."""
    return _score_gray(_prep(rgb), caps_across, aspect)


def min_caps_across(
    rgb: np.ndarray,
    mode: str = "picture",
    threshold: float | None = None,
    aspect: float | None = None,
    candidates: tuple[int, ...] = CANDIDATES,
) -> int:
    """Smallest caps-across whose SSIM clears the threshold; the last candidate
    if none do (image never reads within this range)."""
    a = np.asarray(rgb)
    h, w = a.shape[:2]
    if aspect is None:
        aspect = w / h
    if threshold is None:
        threshold = PATTERN_THRESHOLD if mode == "pattern" else PICTURE_THRESHOLD
    gray = _prep(a)  # prep once, then score every candidate
    for n in candidates:
        if _score_gray(gray, n, aspect) >= threshold:
            return n
    return candidates[-1]
