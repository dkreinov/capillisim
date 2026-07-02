"""Designer: turn a target image into a GridPlan, render it, and simulate how it
reads from a distance.

This is the offline half of the system (Milestone 1): no camera, no projector,
fully testable. It depends on Pillow + numpy but stays otherwise self-contained.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ..core import features
from ..core.geometry import Grid
from ..core.palette import DEFAULT_PALETTE, CapColor, distance, nearest
from ..core.plan import GridPlan, PlannedCell
from ..core.sizing import apparent_fraction

# Perceptual "blend threshold": the angular size below which neighbouring caps
# read as a merged tone (a squint/halftone-blending heuristic, larger than raw
# 1-arcminute acuity). Tunable; calibrate against real photos later.
DEFAULT_BLEND_ARCMIN = 8.0

# Default number of colours when deriving a palette from the image by clustering.
DEFAULT_PALETTE_COLORS = 12


def _rgb_to_lab_np(rgb: np.ndarray) -> np.ndarray:
    """Vectorised sRGB -> CIELAB (D65) for an Nx3 array; mirrors palette.rgb_to_lab."""
    c = np.asarray(rgb, dtype=float) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[:, 0], lin[:, 1], lin[:, 2]
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: np.ndarray) -> np.ndarray:
        return np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=1)


def _sample_pixels(arr: np.ndarray, max_samples: int = 4000, seed: int = 0) -> np.ndarray:
    flat = arr.reshape(-1, 3)
    if len(flat) > max_samples:
        idx = np.random.default_rng(seed).choice(len(flat), max_samples, replace=False)
        flat = flat[idx]
    return flat


def kmeans_palette_lab(
    rgbs, k: int = DEFAULT_PALETTE_COLORS, iters: int = 25, seed: int = 0
) -> list[tuple[int, int, int]]:
    """Cluster colours in CIELAB and return up to `k` representative RGB centroids.

    We cluster perceptually (Euclidean distance in CIELAB ≈ ΔE) but report each
    centroid as the mean RGB of its members, so no inverse Lab->RGB is needed.
    Deterministic for a given seed (k-means++ init).
    """
    rgbs = np.asarray(rgbs, dtype=float)
    if len(rgbs) == 0:
        return []
    lab = _rgb_to_lab_np(rgbs)
    uniq = np.unique(lab, axis=0)
    k = max(1, min(k, len(uniq)))
    rng = np.random.default_rng(seed)

    # k-means++ initialisation for stable, well-spread centroids.
    centers = [lab[rng.integers(len(lab))]]
    for _ in range(1, k):
        d2 = np.min(
            ((lab[:, None, :] - np.array(centers)[None, :, :]) ** 2).sum(2), axis=1
        )
        total = d2.sum()
        probs = d2 / total if total > 0 else np.full(len(lab), 1 / len(lab))
        centers.append(lab[rng.choice(len(lab), p=probs)])
    centers = np.array(centers)

    assign = np.zeros(len(lab), dtype=int)
    for _ in range(iters):
        d2 = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(2)
        new_assign = d2.argmin(1)
        new_centers = np.array(
            [lab[new_assign == j].mean(0) if (new_assign == j).any() else centers[j]
             for j in range(k)]
        )
        if np.array_equal(new_assign, assign) and np.allclose(new_centers, centers):
            assign = new_assign
            break
        assign, centers = new_assign, new_centers

    out: list[tuple[int, int, int]] = []
    for j in range(k):
        members = rgbs[assign == j]
        if len(members):
            out.append(tuple(int(round(v)) for v in members.mean(0)))
    return out


def palette_from_image(
    image: Image.Image,
    k: int = DEFAULT_PALETTE_COLORS,
    inventory: tuple[CapColor, ...] | None = None,
    seed: int = 0,
) -> tuple[CapColor, ...]:
    """Derive a working palette from the image's dominant colours (CIELAB k-means).

    If `inventory` is given (the caps you actually have), return the subset of
    inventory nearest the image's colour clusters — i.e. ``kmeans(image) ∩
    inventory``. Colours the inventory can't represent are handled downstream by
    the reject gate (those cells become holes). Without inventory, the centroids
    themselves are the palette, named by their nearest reference colour.
    """
    arr = np.asarray(image.convert("RGB"))
    centroids = kmeans_palette_lab(_sample_pixels(arr, seed=seed), k=k, seed=seed)
    if not centroids:
        return DEFAULT_PALETTE

    if inventory:
        used: dict[str, CapColor] = {}
        for rgb in centroids:
            cap = nearest(rgb, tuple(inventory))
            used[cap.name] = cap  # dedupe: one image cluster may pick the same cap
        return tuple(used.values())

    out: list[CapColor] = []
    seen: dict[str, int] = {}
    for rgb in centroids:
        base = nearest(rgb, DEFAULT_PALETTE).name
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base}{seen[base]}"
        out.append(CapColor(name, rgb))
    return tuple(out)


def inventory_from_labels(path) -> tuple[CapColor, ...]:
    """Load a legacy ``labels.csv`` (index,r,g,b,...) as inventory."""
    import csv

    caps: list[CapColor] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rgb = (int(row["r"]), int(row["g"]), int(row["b"]))
            caps.append(CapColor(f"cap{row['index']}", rgb))
    return tuple(caps)


def inventory_from_db(path) -> tuple[CapColor, ...]:
    """Load the SQLite cap dataset (caps.db) as inventory."""
    from ..data.store import CapDataset

    with CapDataset(path) as db:
        return tuple(CapColor(f"cap{c.id}", c.rgb) for c in db.caps())


def load_inventory(path) -> tuple[CapColor, ...]:
    """Load inventory from a ``.db`` (preferred) or legacy ``.csv`` file."""
    from pathlib import Path

    return (
        inventory_from_labels(path)
        if Path(path).suffix.lower() == ".csv"
        else inventory_from_db(path)
    )


def plan_from_image(
    image: Image.Image,
    grid: Grid,
    palette: tuple[CapColor, ...] = DEFAULT_PALETTE,
    title: str = "untitled",
    reject_threshold: float | None = None,
    colors: int | None = None,
    inventory: tuple[CapColor, ...] | None = None,
    bare_white: bool = False,
    white_level: int = 238,
    thicken_outlines: bool = False,
) -> GridPlan:
    """Sample `image` at each cap location and quantize to a cap palette.

    Palette selection:
      - default: the fixed reference palette (`DEFAULT_PALETTE`);
      - if `colors` or `inventory` is given: derive the palette from the image by
        CIELAB k-means, intersected with `inventory` when supplied.

    Reject gate: if `reject_threshold` is set, any cell whose target colour is
    farther than that (CIEDE2000) from the best available cap is left as a
    **hole** rather than filled with a poor colour. See docs/COLOR_MATCHING.md.

    Bare-white background: with `bare_white=True`, cells whose sampled colour is
    near-white (every channel >= `white_level`) become holes — the board is left
    bare rather than paved with white caps.
    """
    if colors is not None or inventory is not None:
        palette = palette_from_image(image, k=colors or DEFAULT_PALETTE_COLORS,
                                     inventory=inventory)

    img = image.convert("RGB")
    arr = np.asarray(img)
    img_h, img_w = arr.shape[:2]
    radius_px_x = max(1, int((grid.cap.radius_mm / grid.width_mm) * img_w))
    radius_px_y = max(1, int((grid.cap.radius_mm / grid.height_mm) * img_h))

    cells: list[PlannedCell] = []
    for cell in grid.cells:
        cx = int((cell.x_mm / grid.width_mm) * img_w)
        cy = int((cell.y_mm / grid.height_mm) * img_h)
        x0, x1 = max(0, cx - radius_px_x), min(img_w, cx + radius_px_x + 1)
        y0, y1 = max(0, cy - radius_px_y), min(img_h, cy + radius_px_y + 1)
        patch = arr[y0:y1, x0:x1].reshape(-1, 3)
        mean = tuple(int(v) for v in patch.mean(axis=0)) if patch.size else (0, 0, 0)
        if bare_white and min(mean) >= white_level:
            # near-white background: leave the board bare rather than a white cap
            cells.append(
                PlannedCell(
                    row=cell.row, col=cell.col, x_mm=cell.x_mm, y_mm=cell.y_mm,
                    color_name="", rgb=mean, is_hole=True,
                )
            )
            continue
        cap_color = nearest(mean, palette)
        if reject_threshold is not None and distance(mean, cap_color) > reject_threshold:
            # No cap colour is close enough — leave a hole, keep the wanted colour.
            cells.append(
                PlannedCell(
                    row=cell.row,
                    col=cell.col,
                    x_mm=cell.x_mm,
                    y_mm=cell.y_mm,
                    color_name="",
                    rgb=mean,
                    is_hole=True,
                )
            )
            continue
        cells.append(
            PlannedCell(
                row=cell.row,
                col=cell.col,
                x_mm=cell.x_mm,
                y_mm=cell.y_mm,
                color_name=cap_color.name,
                rgb=cap_color.rgb,
            )
        )

    if thicken_outlines and cells:
        _thicken_outline_cells(cells, palette)

    return GridPlan(
        cap_diameter_mm=grid.cap.diameter_mm,
        width_mm=grid.width_mm,
        height_mm=grid.height_mm,
        cells=cells,
        title=title,
    )


def _cell_grid(cells: list[PlannedCell]) -> tuple[np.ndarray, dict]:
    """Rebuild the (rows, cols, 3) cap-colour grid from a cell list (light = gap)."""
    rows = max(c.row for c in cells) + 1
    cols = max(c.col for c in cells) + 1
    grid = np.full((rows, cols, 3), 255, np.uint8)
    by_rc: dict[tuple[int, int], PlannedCell] = {}
    for c in cells:
        grid[c.row, c.col] = c.rgb
        by_rc[(c.row, c.col)] = c
    return grid, by_rc


def count_thin_outlines(plan: GridPlan) -> int:
    """Cap cells sitting on a ~1-cap-thin dark stroke (likely to vanish at distance)."""
    if not plan.cells:
        return 0
    grid, _ = _cell_grid(plan.cells)
    return features.count_thin_features(grid)


def _thicken_outline_cells(cells: list[PlannedCell], palette: tuple[CapColor, ...]) -> None:
    """Widen ~1-cap-thin dark strokes to 2 caps in-place so outlines survive."""
    grid, by_rc = _cell_grid(cells)
    thick = features.thicken_dark_lines(grid)
    changed = np.any(thick != grid, axis=2)
    for r, c in zip(*np.where(changed)):
        cell = by_rc.get((int(r), int(c)))
        if cell is None:
            continue
        cap = nearest(tuple(int(v) for v in thick[r, c]), palette)
        cell.rgb = cap.rgb
        cell.color_name = cap.name
        cell.is_hole = False


def render_mosaic(
    plan: GridPlan,
    px_per_mm: float = 4.0,
    background: tuple[int, int, int] = (235, 235, 235),
) -> Image.Image:
    """Draw the plan as filled cap-circles for preview/inspection."""
    w = max(1, int(plan.width_mm * px_per_mm))
    h = max(1, int(plan.height_mm * px_per_mm))
    img = Image.new("RGB", (w, h), background)
    draw = ImageDraw.Draw(img)
    r = (plan.cap_diameter_mm / 2.0) * px_per_mm
    for c in plan.cells:
        if c.is_hole:
            continue  # deliberate blank — leave the background showing
        cx, cy = c.x_mm * px_per_mm, c.y_mm * px_per_mm
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(c.rgb))
    return img


def simulate_distance(
    mosaic: Image.Image,
    px_per_mm: float,
    distance_m: float,
    blend_arcmin: float = DEFAULT_BLEND_ARCMIN,
) -> Image.Image:
    """Blur the rendered mosaic to approximate how it reads from `distance_m`.

    Caps merge into tones as they shrink in your field of view. We model that as
    a Gaussian blur whose width grows with viewing distance, so sliding distance
    shows the pattern-up-close vs. portrait-from-afar trade-off.
    """
    blend_rad = math.radians(blend_arcmin / 60.0)
    sigma_mm = distance_m * 1000.0 * math.tan(blend_rad)
    sigma_px = max(0.0, sigma_mm * px_per_mm)
    return mosaic.filter(ImageFilter.GaussianBlur(radius=sigma_px))


def _srgb_to_linear(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def _resample_linear(img: Image.Image, w: int, h: int) -> Image.Image:
    """Area-average `img` down to (w, h) in LINEAR light (physically-correct
    optical colour mixing), then back to sRGB. cv2 INTER_AREA needs float32."""
    import cv2

    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    lin = _srgb_to_linear(arr).astype(np.float32)
    resized = cv2.resize(lin, (max(1, w), max(1, h)), interpolation=cv2.INTER_AREA)
    srgb = _linear_to_srgb(resized)
    out = np.clip(srgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def view_at_distance(
    mosaic: Image.Image,
    mosaic_width_mm: float,
    distance_m: float,
    frame_px: tuple[int, int],
    fov_deg: float = 50.0,
    board: tuple[int, int, int] = (230, 230, 230),
) -> Image.Image:
    """How the sharp mosaic reads from `distance_m`, in a fixed field-of-view frame.

    As you step back the mosaic subtends a smaller angle, so it SHRINKS inside a
    fixed `frame_px` frame while STAYING SHARP. Neighbouring caps merge because
    the whole picture is area-resampled to the pixel size it subtends — in linear
    light, so the colour mixing is physically correct (not a growing blur). The
    surround is left as bare board colour.
    """
    frame_w, frame_h = frame_px
    frac = apparent_fraction(mosaic_width_mm / 1000.0, distance_m, fov_deg)
    mw, mh = mosaic.size

    target_w = max(1, int(round(frac * frame_w)))
    target_h = max(1, int(round(target_w * mh / mw)))
    if target_h > frame_h:  # keep the whole mosaic inside the frame
        target_h = frame_h
        target_w = max(1, int(round(target_h * mw / mh)))

    resized = _resample_linear(mosaic, target_w, target_h)
    frame = Image.new("RGB", (frame_w, frame_h), board)
    frame.paste(resized, ((frame_w - target_w) // 2, (frame_h - target_h) // 2))
    return frame


def demo_image(size: int = 512) -> Image.Image:
    """A synthetic target so the pipeline is runnable without supplying art."""
    img = Image.new("RGB", (size, size), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    draw.ellipse([size * 0.2, size * 0.15, size * 0.8, size * 0.75], fill=(225, 200, 70))
    draw.ellipse([size * 0.34, size * 0.32, size * 0.44, size * 0.42], fill=(28, 28, 28))
    draw.ellipse([size * 0.56, size * 0.32, size * 0.66, size * 0.42], fill=(28, 28, 28))
    draw.arc([size * 0.34, size * 0.40, size * 0.66, size * 0.66], 20, 160, fill=(190, 40, 45), width=int(size * 0.03))
    draw.rectangle([0, int(size * 0.8), size, size], fill=(40, 80, 160))
    return img
