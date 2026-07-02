"""Render a mosaic from actual cap images (real + fake), not flat colour disks.

Each planned cell is filled with the library cap whose colour is perceptually
closest, pasted as a circular RGBA tile. The result looks like caps up close;
blurred by ``planner_designer.simulate_distance`` it reads as the picture — the
"too close you see caps, far away you see the image" simulation.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from ..core.palette import RGB, ciede2000, rgb_to_lab
from ..core.plan import GridPlan
from .fake_caps import CapImage, fake_cap_library, render_fake_cap


def _load_circular(path: str, size: int) -> Image.Image | None:
    """A real cap crop auto-cropped to its disc and masked to a circle (RGBA).

    Captured crops frame the cap inconsistently (off-centre, with background), so
    a plain resize makes cap sizes look uneven. Detect the cap disc and cut it out
    tightly so every real cap ends up the same size, like the procedural ones.
    """
    from .cap_crop import cap_cutout_from_path

    try:
        return cap_cutout_from_path(path, size)
    except Exception:  # noqa: BLE001 - a bad crop just drops that one cap
        return None


@lru_cache(maxsize=8)
def _real_caps(db_path: str, size: int, mtime: float) -> tuple[CapImage, ...]:
    """Real caps from the dataset as circular tiles, cached (mtime busts it)."""
    from ..data.store import CapDataset

    caps: list[CapImage] = []
    with CapDataset(db_path) as db:
        for c in db.caps(with_frames=True):
            if not c.frames:
                continue
            im = _load_circular(c.frames[0].path, size)
            if im is not None:
                caps.append(CapImage(tuple(c.rgb), im))
    return tuple(caps)


def _jitter(rgb: RGB, amount: int, seed: int) -> RGB:
    """Small deterministic per-channel shade shift, so variants aren't identical."""
    import random

    rng = random.Random(seed)
    return tuple(max(0, min(255, v + rng.randint(-amount, amount))) for v in rgb)


def build_library(
    palette: list[RGB],
    db_path: str | None = None,
    size: int = 64,
    seed: int = 0,
    markings: bool = True,
    variants: int = 3,
) -> list[CapImage]:
    """A diverse cap library: several shade/logo variants per palette colour plus
    the real caps from ``db_path``. Real caps are loaded once and cached. Variety
    (different logos and slight shade shifts) makes the mosaic read like a jumble
    of actual caps rather than flat discs."""
    lib: list[CapImage] = []
    for i, c in enumerate(palette):
        c = tuple(int(v) for v in c)
        for v in range(max(1, variants)):
            jit = c if v == 0 else _jitter(c, 14, seed + i * 101 + v)
            lib.append(render_fake_cap(jit, size=size, seed=seed + i * 7 + v * 3,
                                       markings=markings))
    if db_path and Path(db_path).exists():
        lib.extend(_real_caps(db_path, size, Path(db_path).stat().st_mtime))
    return lib


def render_mosaic_caps(
    plan: GridPlan,
    cap_lib: list[CapImage],
    px_per_cap: int = 24,
    background: RGB = (235, 235, 235),
    variety: bool = True,
) -> Image.Image:
    """Draw the plan by tiling caps into each cell. With `variety`, each cell picks
    among the caps closest in colour (varying logos/shades), keyed by its position,
    so equal-colour regions aren't a wall of identical tiles."""
    if not cap_lib:
        raise ValueError("cap_lib is empty")
    pitch = plan.cap_diameter_mm
    ppm = px_per_cap / pitch
    w = max(1, round(plan.width_mm * ppm))
    h = max(1, round(plan.height_mm * ppm))
    canvas = Image.new("RGB", (w, h), background)

    labs = [(cap, rgb_to_lab(cap.rgb)) for cap in cap_lib]
    groups: dict[RGB, list[CapImage]] = {}

    def candidates(key: RGB) -> list[CapImage]:
        if key not in groups:
            lab = rgb_to_lab(key)
            ranked = sorted(((ciede2000(lab, l), cap) for cap, l in labs),
                            key=lambda t: t[0])
            best = ranked[0][0]
            near = [cap for de, cap in ranked if de <= best + 6.0][:6]
            groups[key] = near or [ranked[0][1]]
        return groups[key]

    tiles: dict[int, Image.Image] = {}
    for cell in plan.cells:
        if cell.is_hole:
            continue
        group = candidates(tuple(cell.rgb))
        idx = (cell.row * 31 + cell.col) % len(group) if variety else 0
        cap = group[idx]
        tile = tiles.get(id(cap))
        if tile is None:
            tile = cap.image.resize((px_per_cap, px_per_cap), Image.LANCZOS)
            tiles[id(cap)] = tile
        cx, cy = cell.x_mm * ppm, cell.y_mm * ppm
        canvas.paste(tile, (round(cx - px_per_cap / 2), round(cy - px_per_cap / 2)), tile)
    return canvas
