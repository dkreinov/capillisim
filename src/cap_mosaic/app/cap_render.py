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


def _load_circular(path: str, size: int,
                   radius_frac: float | None = None) -> Image.Image | None:
    """A real cap crop auto-cropped to its disc and masked to a circle (RGBA).

    Captured crops frame the cap inconsistently (off-centre, with background), so
    a plain resize makes cap sizes look uneven. With ``radius_frac`` (the cap's
    known radius as a fraction of the crop width, from the card's mm-true
    geometry) the cut is exact; without it the disc is detected from pixels.
    """
    from .cap_crop import cap_cutout_from_path

    try:
        return cap_cutout_from_path(path, size, radius_frac=radius_frac)
    except Exception:  # noqa: BLE001 - a bad crop just drops that one cap
        return None


_LEGACY_SPAN_MM = 37.8  # crop window width implied for rows without crop_span_mm


def _best_frame(c) -> object:
    """The frame whose colour is truest to the cap's canonical (median) colour.

    Frame 0 is just 'first in the burst' — it can be a pale mis-capture (hand
    still in frame, glare, haze) while later frames are crisp. The cap's stored
    colour is the median across frames, so the closest frame is the honest face.
    """
    scored = [f for f in c.frames if f.rgb is not None]
    if not scored:
        return c.frames[0]
    ref = rgb_to_lab(tuple(c.rgb))
    return min(scored, key=lambda f: ciede2000(ref, rgb_to_lab(tuple(f.rgb))))


def _cutout_cached(cutout_dir: Path, cap_id: int, frame_index: int, path: str,
                   size: int, radius_frac: float | None) -> Image.Image | None:
    """The cap's normalized cutout, served from ``dataset/cutouts/`` when fresh.

    Cropping 400+ caps live (imread + circle refinement each) is the slow part;
    the cutout is deterministic per (crop file, size), so it is computed once and
    persisted next to the db. Stale (source newer) or missing -> recomputed. The
    frame index is part of the name so a changed frame CHOICE busts the cache.
    """
    out = cutout_dir / f"cap{cap_id:04d}_f{frame_index}_{size}.png"
    src = Path(path)
    if out.exists() and src.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        try:
            return Image.open(out).convert("RGBA")
        except OSError:
            pass
    im = _load_circular(str(src), size, radius_frac)
    if im is not None:
        cutout_dir.mkdir(parents=True, exist_ok=True)
        im.save(out)
    return im


@lru_cache(maxsize=8)
def _real_caps(db_path: str, size: int, mtime: float) -> tuple[CapImage, ...]:
    """Real caps from the dataset as circular tiles, cached (mtime busts it)."""
    from ..data.store import CapDataset

    cutout_dir = Path(db_path).parent / "cutouts"
    caps: list[CapImage] = []
    with CapDataset(db_path) as db:
        for c in db.caps(with_frames=True):
            if not c.frames:
                continue
            # the card geometry gives the cap's exact radius inside the crop
            span = c.crop_span_mm or _LEGACY_SPAN_MM
            rf = (c.diameter_mm / span) / 2.0 if c.diameter_mm else None
            fr = _best_frame(c)
            im = _cutout_cached(cutout_dir, c.id, fr.frame_index, fr.path, size, rf)
            if im is not None:
                # match by the at-distance (mosaic) colour so a busy cap lands
                # where its MIX belongs, not where its field colour belongs
                caps.append(CapImage(tuple(c.mosaic_rgb or c.rgb), im, real=True))
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
    background: RGB = (60, 45, 35),
    variety: bool = True,
    real_only: bool = False,
    highlight: RGB | None = None,
) -> Image.Image:
    """Draw the plan by tiling round caps into each cell. With `variety`, each cell
    picks among the caps closest in colour (varying logos/shades), keyed by its
    position, so equal-colour regions aren't a wall of identical tiles.

    Caps are round, so the small gaps between glued caps show the physical
    **backing board** — one solid `background` colour (wood / paper / paint), not
    the cap colour. Holes show the same board (a deliberate empty cell, uncounted).
    With `real_only`, cells are filled only from photographed caps when the library
    has any. With `highlight` set to a cap colour, only cells of that colour render
    fully; every other cap is ghosted (near-transparent) so you can see where that
    one colour goes.
    """
    if not cap_lib:
        raise ValueError("cap_lib is empty")
    pool = [c for c in cap_lib if getattr(c, "real", False)] if real_only else []
    if not pool:
        pool = cap_lib
    pitch = plan.cap_diameter_mm
    ppm = px_per_cap / pitch
    w = max(1, round(plan.width_mm * ppm))
    h = max(1, round(plan.height_mm * ppm))
    canvas = Image.new("RGB", (w, h), tuple(background))

    labs = [(cap, rgb_to_lab(cap.rgb)) for cap in pool]
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

    def dim(tile: Image.Image) -> Image.Image:
        r, g, b, a = tile.split()
        return Image.merge("RGBA", (r, g, b, a.point(lambda v: v * 12 // 100)))

    half = px_per_cap / 2
    tiles: dict[tuple[int, bool], Image.Image] = {}
    for cell in plan.cells:
        if cell.is_hole:
            continue  # deliberate empty cell -> board shows, not a cap, uncounted
        group = candidates(tuple(cell.rgb))
        idx = (cell.row * 31 + cell.col) % len(group) if variety else 0
        cap = group[idx]
        ghost = highlight is not None and tuple(cell.rgb) != highlight
        tile = tiles.get((id(cap), ghost))
        if tile is None:
            tile = cap.image.resize((px_per_cap, px_per_cap), Image.LANCZOS)
            if ghost:
                tile = dim(tile)
            tiles[(id(cap), ghost)] = tile
        cx, cy = cell.x_mm * ppm, cell.y_mm * ppm
        canvas.paste(tile, (round(cx - half), round(cy - half)), tile)
    return canvas
