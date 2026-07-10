"""FastAPI backend for the Mosaic Estimator.

Endpoints:
- ``POST /upload``            -> store an image, return its id + dimensions.
- ``GET  /estimate``          -> solve size<->distance, legibility, BOM, effective colours.
- ``GET  /simulate``          -> a cap-rendered mosaic (PNG), optionally blurred for distance.
"""

from __future__ import annotations

import io
import os
from collections import Counter
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont

from ...core import critique as critique_mod
from ...core import estimator
from ...core.geometry import Cap, grid_for_caps_across
from ...core.sizing import apparent_fraction
from ...core.palette import preset_palette
from ..cap_map import render_cap_map
from ..cap_render import build_library, render_mosaic_caps
from ..planner_designer import count_thin_outlines, plan_from_image, view_at_distance

app = FastAPI(title="Capillisim Mosaic Estimator")

_IMAGES: dict[str, Image.Image] = {}
_COUNTER = {"n": 0}
# Use the captured cap dataset for realistic caps + BOM when it exists.
_DB = Path("dataset/caps.db")
_MAX_CAPS_ACROSS = 140  # render resolution ceiling; bigger size -> more detail
_SIM_WIDTH_PX = 1200  # target simulation width; tile px adapts to keep it bounded
_FRAME_PX = (900, 650)  # fixed field-of-view frame the mosaic shrinks inside
_STAGE_BG = (20, 24, 38)  # dark-space wall behind the framed piece (= CSS --surface-1)
_INV_TOL = 12.0  # CIEDE2000 within which an owned cap counts toward a BOM colour


_STATIC = Path(__file__).parent / "static"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    try:
        img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad upload
        raise HTTPException(400, f"could not read image: {exc}") from exc
    _COUNTER["n"] += 1
    iid = str(_COUNTER["n"])
    _IMAGES[iid] = img
    return {"id": iid, "width": img.width, "height": img.height,
            "aspect": img.width / img.height}


def _hex_rgb(s: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    """Parse '#rrggbb' (or 'rrggbb') to an RGB tuple; fall back to `default`."""
    s = (s or "").strip().lstrip("#")
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return default


def _get(image_id: str) -> Image.Image:
    img = _IMAGES.get(image_id)
    if img is None:
        raise HTTPException(404, "unknown image id (upload first)")
    return img


@app.get("/image")
def image(image_id: str) -> Response:
    """The stored image as PNG (used to preview a cropped region)."""
    buf = io.BytesIO()
    _get(image_id).save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/crop")
def crop(image_id: str, x0: float, y0: float, x1: float, y1: float) -> dict:
    """Crop a stored image to a fractional box (0..1) and store it as a new id."""
    img = _get(image_id)
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    box = (int(x0 * img.width), int(y0 * img.height),
           int(x1 * img.width), int(y1 * img.height))
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        raise HTTPException(400, "selection too small")
    sub = img.crop(box)
    _COUNTER["n"] += 1
    iid = str(_COUNTER["n"])
    _IMAGES[iid] = sub
    return {"id": iid, "width": sub.width, "height": sub.height,
            "aspect": sub.width / sub.height}


# Caches keyed by image id: the legibility floor (image+mode only) and the plan
# (image+caps+colors). Both are size/distance-independent, so slider drags reuse
# them instead of recomputing k-means and SSIM every request.
_FLOORS: dict[tuple, int] = {}
_PLANS: dict[tuple, object] = {}


def _floor(image_id: str, img: Image.Image, mode: str) -> int:
    key = (image_id, mode)
    if key not in _FLOORS:
        _FLOORS[key] = estimator.min_caps_across(
            np.asarray(img), mode=mode, aspect=img.width / img.height
        )
    return _FLOORS[key]


def _plan(image_id: str, img: Image.Image, caps_across: int, colors: int,
          bare_white: bool = True, preset: str | None = None, thicken: bool = False,
          dither: bool = False, from_my_caps: bool = False,
          own_threshold: float = 12.0, unlimited_stock: bool = False):
    caps_across = max(1, min(caps_across, _MAX_CAPS_ACROSS))
    key = (image_id, caps_across, colors, bare_white, preset, thicken, dither,
           from_my_caps, own_threshold, unlimited_stock)
    if key not in _PLANS:
        grid = grid_for_caps_across(caps_across, img.width / img.height, Cap())
        if from_my_caps and _DB.exists():
            from ..cap_stock import load_stock

            groups = load_stock(str(_DB))
            if unlimited_stock:
                # "assume unlimited stock": use every owned cap COLOUR as an
                # unlimited palette on the full slider-resolution grid — each cell
                # takes its nearest owned colour, no count limit / holes. Shows the
                # best case if you had enough of every colour you own.
                from ...core.palette import CapColor

                palette = tuple(CapColor(g.label, tuple(int(v) for v in g.rgb))
                                for g in groups)
                _PLANS[key] = plan_from_image(img, grid, palette=palette,
                                              bare_white=bare_white,
                                              thicken_outlines=thicken, dither=dither)
                return _PLANS[key]
            # "Only caps I own": keep the owned caps within own_threshold ΔE00 of
            # a colour the image needs, then SHRINK the grid so its cell count ~
            # the usable-cap count, so each owned cap fills one cell and the image
            # reads instead of drowning in holes. The size slider's resolution is
            # overridden by this derived piece (see caps-own-fit-plan.md).
            from ..planner_designer import (
                fit_caps_across, plan_from_inventory, usable_groups,
            )

            usable = usable_groups(groups, img, own_threshold,
                                   filter_k=max(colors, 16))
            if not usable:  # threshold excludes every cap — fall back to full stock
                usable = groups
            x = sum(g.count for g in usable)  # usable cap count = target cells
            aspect = img.width / img.height
            fit_across = min(fit_caps_across(x, aspect), _MAX_CAPS_ACROSS)
            fit_grid = grid_for_caps_across(fit_across, aspect, Cap())
            _PLANS[key] = plan_from_inventory(img, fit_grid, usable,
                                              bare_white=bare_white)
            return _PLANS[key]
        pal = preset_palette(preset) if preset else None
        if pal is not None:  # a curated palette overrides k-means colour derivation
            _PLANS[key] = plan_from_image(img, grid, palette=pal, bare_white=bare_white,
                                          thicken_outlines=thicken, dither=dither)
        else:
            _PLANS[key] = plan_from_image(img, grid, colors=colors, bare_white=bare_white,
                                          thicken_outlines=thicken, dither=dither)
    return _PLANS[key]


def _own_geometry(res: dict, plan) -> int:
    """In caps-I-own mode the fitted plan (sized to the usable-cap count) drives
    the geometry, not the size slider. Patch the solve result to the plan's real
    piece and return its caps-across."""
    across = max(1, round(plan.width_mm / plan.cap_diameter_mm))
    res["caps_across"] = across
    res["width_mm"] = plan.width_mm
    res["height_mm"] = plan.height_mm
    return across


def _solve(img: Image.Image, image_id: str, mode: str, pitch: float,
           size_mm: float | None, distance_m: float | None) -> dict:
    arr = np.asarray(img)
    floor = _floor(image_id, img, mode)
    if size_mm is not None:
        return estimator.solve_from_size(arr, size_mm, mode=mode, pitch_mm=pitch,
                                         min_caps=floor)
    if distance_m is not None:
        return estimator.solve_from_distance(arr, distance_m, mode=mode,
                                             pitch_mm=pitch, min_caps=floor)
    raise HTTPException(400, "provide either size_mm or distance_m")


@app.get("/pattern")
def pattern(kind: str = "gradient") -> dict:
    """A pattern laid out from the OWNED caps (every cap exactly once, zero
    colour error), rendered sharp and stored as a new image — so it drops
    straight into the version strip / simulate / cap-map flow."""
    if not _DB.exists():
        raise HTTPException(404, "no cap inventory (scan caps first)")
    from ...core.pattern import KINDS, pattern_plan
    from ..cap_stock import load_stock

    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(KINDS)}")
    stock = [(g.rgb, g.count) for g in load_stock(str(_DB))]
    plan = pattern_plan(kind, stock)
    palette = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    # every colour IS a real cap, so render from the photographed caps only —
    # procedural fillers would muddy the pattern's structure
    lib = build_library(palette, db_path=str(_DB), size=64)
    img = render_mosaic_caps(plan, lib, px_per_cap=22, real_only=True)
    _COUNTER["n"] += 1
    iid = str(_COUNTER["n"])
    _IMAGES[iid] = img
    return {"id": iid, "width": img.width, "height": img.height,
            "aspect": img.width / img.height, "kind": kind,
            "caps": sum(1 for c in plan.cells if not c.is_hole)}


@app.get("/palette_prompt")
def palette_prompt() -> dict:
    """A ready-to-paste AI-image prompt constrained to the owned palette."""
    if not _DB.exists():
        raise HTTPException(404, "no cap inventory (scan caps first)")
    from ..cap_stock import load_stock

    groups = sorted(load_stock(str(_DB)), key=lambda g: -g.count)
    total = sum(g.count for g in groups)
    top = groups[:8]
    hexes = ", ".join(f"#{g.rgb[0]:02x}{g.rgb[1]:02x}{g.rgb[2]:02x} (~{g.count} caps)"
                      for g in top)
    prompt = (
        f"Bold flat poster artwork for a bottle-cap mosaic of about {total} tiles "
        f"(~{int(total ** 0.5)} across). Use ONLY these colours, roughly in these "
        f"proportions: {hexes}. Thick outlines, simple bold shapes, high contrast, "
        f"no fine detail, no text, plain background in the most plentiful colour. "
        f"The subject must stay recognizable at very low resolution."
    )
    return {"prompt": prompt, "colors": len(top), "caps": total}


@app.get("/caps_count")
def caps_count() -> dict:
    """How many caps are in the scanned inventory (0 when caps.db is absent)."""
    if not _DB.exists():
        return {"count": 0}
    from ..planner_designer import load_inventory

    return {"count": len(load_inventory(str(_DB)))}


@app.post("/scanner/launch")
def scanner_launch() -> dict:
    """Open the cap-scanning camera app on this computer.

    The server runs on the user's own machine, so spawning the OpenCV capture
    window locally is exactly what "scan more caps" means here. Detached: the
    scanner outlives web requests and closes from its own window (Q).
    """
    import subprocess
    import sys

    args = [sys.executable, "-m", "cap_mosaic.app.cap_capture",
            "--out", "dataset", "--auto"]
    kw = {"cwd": str(Path.cwd()),
          "env": {**os.environ, "PYTHONPATH": "src"}}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    p = subprocess.Popen(args, **kw)  # noqa: S603 - fixed local command
    return {"launched": True, "pid": p.pid}


# ── inventory browser: view the cap DB, delete mis-scans with the mouse ──────


@app.get("/inventory")
def inventory_page() -> FileResponse:
    return FileResponse(_STATIC / "inventory.html")


@app.get("/inventory/caps")
def inventory_caps() -> list[dict]:
    """Every cap in the DB, newest first, with what the browser grid shows."""
    if not _DB.exists():
        return []
    from ...data.store import CapDataset

    with CapDataset(_DB) as db:
        caps = db.caps(with_frames=True)
    return [{
        "id": c.id, "field": list(c.rgb),
        "mosaic": list(c.mosaic_rgb) if c.mosaic_rgb else None,
        "diameter_mm": c.diameter_mm, "size_class": c.size_class,
        "captured_at": c.captured_at, "notes": c.notes,
        "has_crop": bool(c.frames),
    } for c in reversed(caps)]


@app.get("/inventory/crop/{cap_id}")
def inventory_crop(cap_id: int) -> FileResponse:
    """First stored crop image of a cap (the grid thumbnail)."""
    if not _DB.exists():
        raise HTTPException(404, "no cap database")
    from ...data.store import CapDataset

    with CapDataset(_DB) as db:
        for c in db.caps(with_frames=True):
            if c.id == cap_id:
                for f in c.frames:
                    if Path(f.path).exists():
                        return FileResponse(f.path, media_type="image/png")
                raise HTTPException(404, "crop file missing")
    raise HTTPException(404, f"no cap #{cap_id}")


# Each cutout carries a few px of soft shadow/rim beyond the cap's colour, so
# packing circles at pitch == diameter leaves those pale rims meeting and reads
# as a gap. Nesting the pitch in slightly overlaps the rims into thin grout
# lines — the caps read as touching, like a real tight-glued wall.
_PACK = 0.92


# The believe-your-eyes colour test is a real zoom-out at a CONSTANT frame
# size: the coloured area never shrinks into bare board — instead, stepping
# back fits MORE, SMALLER caps into the same window (each subtends less), and
# many small navy+logo caps average to the flat mosaic colour in your eye. So
# far away the tiled half is fine cap texture that reads as the same colour as
# the solid swatch — not a magnified fake blob.
_D0 = 0.5           # reference distance (m): caps_left == _BASE_CAPS here
_BASE_CAPS = 6      # caps across the tiled half at _D0
_MAX_CAPS = 140     # cap keeps caps >= ~2px so it stays cap texture, not noise


def _caps_across_for(distance_m: float) -> int:
    """How many caps span the tiled half at this distance (∝ distance).

    Stepping back, a 3 cm cap subtends less, so more caps fit the same window.
    """
    n = int(round(_BASE_CAPS * distance_m / _D0))
    return max(_BASE_CAPS, min(_MAX_CAPS, n))


def _label_font(size: int):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


_SS_W = 1920  # supersample width so caps always tile with correct ~9% grout


def _render_wall(cut: Image.Image, caps_left: int, frame: tuple[int, int],
                 board: tuple[int, int, int], mosaic: tuple[int, int, int]) -> Image.Image:
    """Constant-size frame: LEFT half hex-packed caps sized to fit `caps_left`
    across, RIGHT half the solid mosaic colour. More caps => smaller caps.

    Painted and blended entirely in LINEAR light: shrinking/blending caps in
    sRGB darkens a navy+white cap to the wrong colour (its sRGB mean is far from
    its linear mean, which is the stored mosaic value). And the caps are drawn
    at a SUPERSAMPLED width (so they always tile with the real ~9% grout, never
    leaking extra board as they shrink) then area-downsampled to the frame — so
    far away the tiled half converges to the mosaic colour plus a *constant*
    grout dilution, exactly as a real wall reads.
    """
    import cv2

    from ..planner_designer import _linear_to_srgb, _srgb_to_linear

    fw, fh = frame
    ss_w = _SS_W
    ss_h = int(round(fh * ss_w / fw))
    half = ss_w // 2
    tile = max(6, int(round(half / caps_left)))  # >=6px: clean circle + true grout

    ca = np.asarray(cut.convert("RGBA")).astype(np.float32) / 255.0
    rgb_lin = _srgb_to_linear(ca[..., :3]).astype(np.float32)
    alpha = ca[..., 3:4]
    prem = cv2.resize(rgb_lin * alpha, (tile, tile), interpolation=cv2.INTER_AREA)
    a_small = cv2.resize(alpha, (tile, tile), interpolation=cv2.INTER_AREA)[..., None]

    buf = np.empty((ss_h, ss_w, 3), np.float32)
    buf[:] = _srgb_to_linear(np.asarray(board, np.float32) / 255.0)

    def blit(x: int, y: int) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(ss_w, x + tile), min(ss_h, y + tile)
        if x1 <= x0 or y1 <= y0:
            return
        p = prem[y0 - y:y1 - y, x0 - x:x1 - x]
        a = a_small[y0 - y:y1 - y, x0 - x:x1 - x]
        buf[y0:y1, x0:x1] = p + (1.0 - a) * buf[y0:y1, x0:x1]  # premultiplied over

    pitch = max(1, int(round(tile * _PACK)))
    row_h = max(1, int(round(pitch * 0.8660254)))
    for iy in range(-1, ss_h // row_h + 2):
        # offset rows bleed one pitch left so the margin is full cap, not board
        x = (pitch // 2 - pitch) if iy % 2 else 0
        while x < half:
            blit(x, iy * row_h)
            x += pitch
    buf[:, half:] = _srgb_to_linear(np.asarray(mosaic, np.float32) / 255.0)

    small = cv2.resize(buf, (fw, fh), interpolation=cv2.INTER_AREA)  # linear-light merge
    out = np.clip(_linear_to_srgb(small) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def _view_test(cut: Image.Image, mosaic: tuple[int, int, int],
               board: tuple[int, int, int], distance_m: float,
               frame: tuple[int, int] = (640, 420)) -> Image.Image:
    """One frame of the colour test at `distance_m`, with the distance labelled.

    The frame size is constant; distance only changes how small/many the caps
    are (a real zoom-out), so the coloured area stays put and you can always
    read the colour.
    """
    img = _render_wall(cut, _caps_across_for(distance_m), frame, board, mosaic)
    d = ImageDraw.Draw(img)
    txt = f"{distance_m:.1f} m"
    f = _label_font(20)
    l, t, r, b = d.textbbox((0, 0), txt, font=f)
    d.rectangle([10, 10, 10 + (r - l) + 18, 10 + (b - t) + 14], fill=(0, 0, 0))
    d.text((19, 14 - t), txt, font=f, fill=(255, 255, 255))
    return img


@app.get("/inventory/test/{cap_id}")
def inventory_test(cap_id: int, distance_m: float = Query(2.0, ge=0.3, le=40.0),
                   bg: str = Query("#ffffff")) -> Response:
    """The believe-your-eyes colour test for one scanned cap, at `distance_m`.

    A constant-size frame — LEFT half your caps tiled, RIGHT half the solid
    stored MOSAIC colour. The coloured area never shrinks into bare board; a
    larger distance just fits MORE, SMALLER caps into the same window (a real
    zoom-out). Far away the tiled half becomes fine cap texture that reads as
    the same colour as the swatch — so if the two halves match, the mosaic
    colour is what your eye truly gets. The distance is labelled on the frame.

    ``bg`` sets the board behind the caps — selectable because the surround
    shifts perceived colour (simultaneous contrast); white by default.
    """
    if not _DB.exists():
        raise HTTPException(404, "no cap database")
    from ...data.store import CapDataset, canonical_diameter_mm
    from ..cap_crop import cap_cutout_from_path

    with CapDataset(_DB) as db:
        cap = next((c for c in db.caps(with_frames=True) if c.id == cap_id), None)
    if cap is None:
        raise HTTPException(404, f"no cap #{cap_id}")
    path = next((f.path for f in cap.frames if Path(f.path).exists()), None)
    if path is None:
        raise HTTPException(404, "crop file missing")
    tile = 48
    # dataset crops have known geometry: cap class size over the crop span
    mm = canonical_diameter_mm(cap.size_class) or cap.diameter_mm or 32.1
    span = cap.crop_span_mm or 37.8
    cut = cap_cutout_from_path(path, tile, radius_frac=mm / span / 2.0)
    if cut is None:
        raise HTTPException(500, "could not cut out the cap")
    board = _hex_rgb(bg, (255, 255, 255))
    out = _view_test(cut, tuple(cap.mosaic_rgb or cap.rgb), board, distance_m)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.delete("/inventory/caps/{cap_id}")
def inventory_delete(cap_id: int) -> dict:
    """Delete a cap: its DB row (frames/embeddings cascade) AND its crop files."""
    if not _DB.exists():
        raise HTTPException(404, "no cap database")
    from ...data.store import CapDataset

    with CapDataset(_DB) as db:
        paths = [f.path for c in db.caps(with_frames=True) if c.id == cap_id
                 for f in c.frames]
        ok = db.delete_cap(cap_id)
    if not ok:
        raise HTTPException(404, f"no cap #{cap_id}")
    for p in paths:
        try:
            Path(p).unlink()
        except OSError:
            pass
    return {"deleted": cap_id}


_CRITIQUE: dict[tuple, dict] = {}
_LLM_CRITIQUE: dict[str, dict] = {}


@app.get("/critique")
def critique(image_id: str, mode: str = "picture", pitch_mm: float = 32.0,
             llm: bool = False) -> dict:
    """Heuristic 'is this a good cap-art image?' score + tips + recommended
    settings. With ``llm=true``, also ask the Qwen vision judge (needs QWEEN_KEY;
    cached per image so repeat clicks are free)."""
    img = _get(image_id)
    key = (image_id, mode)
    if key not in _CRITIQUE:
        _CRITIQUE[key] = critique_mod.critique(
            np.asarray(img.convert("RGB")), mode=mode, pitch_mm=pitch_mm)
    res = dict(_CRITIQUE[key])
    if llm:
        if image_id not in _LLM_CRITIQUE:
            from ..llm_judge import qwen_judge
            try:
                _LLM_CRITIQUE[image_id] = qwen_judge(img)
            except Exception as exc:  # noqa: BLE001 - no key / network / quota
                _LLM_CRITIQUE[image_id] = {"error": str(exc)}
        res["llm"] = _LLM_CRITIQUE[image_id]
    return res


@app.get("/estimate")
def estimate(
    image_id: str,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    size_mm: float | None = Query(None),
    distance_m: float | None = Query(None),
    colors: int = 12,
    bare_white: bool = True,
    preset: str | None = None,
    thicken: bool = False,
    dither: bool = False,
    inventory: bool = False,
    from_my_caps: bool = False,
    own_threshold: float = 12.0,
    unlimited_stock: bool = False,
) -> dict:
    """Solve one axis from the other in a single call. When both size_mm and
    distance_m are given, size drives the geometry and distance drives the
    read-quality + effective-colour readout."""
    img = _get(image_id)
    primary_size = size_mm if size_mm is not None else None
    res = _solve(img, image_id, mode, pitch_mm, primary_size, distance_m)

    if size_mm is not None and distance_m is not None:
        res["distance_m"] = round(distance_m, 2)
        res["read_quality"] = estimator.read_quality(pitch_mm, distance_m)

    plan = _plan(image_id, img, res["caps_across"], colors, bare_white=bare_white,
                 preset=preset, thicken=thicken, dither=dither,
                 from_my_caps=from_my_caps, own_threshold=own_threshold,
                 unlimited_stock=unlimited_stock)
    counts = Counter(tuple(c.rgb) for c in plan.cells if not c.is_hole)
    palette = list(counts.keys())

    own_mode = from_my_caps and _DB.exists()
    # the count-limited "own" plan is a small FITTED piece; unlimited-stock keeps
    # the full slider-size piece (like the ideal palette), so its geometry stands.
    own_fitted = own_mode and not unlimited_stock
    if own_fitted:
        # the fitted piece (grid sized to usable caps) overrides the slider size
        _own_geometry(res, plan)
    view_d = res.get("distance_m") or res.get("recommended_distance_m") or 5.0

    if own_mode:
        # how much of the owned stock this plan spends, and how many qualified
        used = sum(1 for c in plan.cells if not c.is_hole)
        from ..planner_designer import load_inventory
        res["stock_used"] = {"used": used, "owned": len(load_inventory(str(_DB))),
                             "usable": plan.count, "unlimited": unlimited_stock}

    # Report caps you actually buy: the area estimate counts the whole panel, but
    # a removed/bare-white background leaves holes with no cap. total_caps is the
    # real (background-excluded) count; panel_caps keeps the full-panel figure.
    # In caps-I-own mode the panel IS the fitted grid, so use its cell count.
    res["panel_caps"] = plan.count if own_mode else res["total_caps"]
    res["total_caps"] = sum(counts.values())
    res["holes"] = plan.hole_count

    res["bom"] = {"#%02x%02x%02x" % rgb: n for rgb, n in counts.most_common()}
    res["colors_used"] = len(palette)
    res["effective_colors"] = len(estimator.effective_colors(palette, view_d, pitch_mm))
    # Smallest piece that still reads + the closest distance it reads from.
    min_w_m, closest_m = estimator.minimal_size(res["min_caps_across"], pitch_mm)
    res["min_size_m"] = round(min_w_m, 2)
    res["closest_distance_m"] = round(closest_m, 2)
    # Share of the viewer's field of view the piece fills at the current distance
    # (drives the framed-view readout; matches view_at_distance's shrink).
    res["apparent_pct"] = round(100.0 * apparent_fraction(res["width_mm"] / 1000.0, view_d))
    # Thin dark outlines (~1 cap wide) tend to vanish at distance; flag them so
    # the user can enlarge or turn on thicken.
    thin = count_thin_outlines(plan)
    res["thin_features"] = thin
    if thin and not thicken:
        res["thin_hint"] = (
            f"{thin} cap(s) sit on ~1-cap-thin outlines that may vanish at "
            f"distance — enlarge the piece or enable 'thicken outlines'."
        )

    # Inventory gap: match your scanned caps (caps.db) against the BOM. Report
    # only — the plan is not constrained by what you own.
    if inventory and _DB.exists():
        res["inventory"], res["inventory_totals"] = _inventory_report(counts)
    return res


def _inventory_report(need: Counter) -> tuple[dict, dict]:
    """have / need / short per BOM colour from caps.db (greedy nearest, dE00<=12)."""
    from ..planner_designer import load_inventory
    from ...core.palette import ciede2000, rgb_to_lab

    inv = load_inventory(str(_DB))
    bom_labs = [(rgb, rgb_to_lab(rgb)) for rgb in need]
    have = {rgb: 0 for rgb in need}
    for cap in inv:  # assign each owned cap to its nearest BOM colour within dE00 12
        clab = rgb_to_lab(cap.rgb)
        best_rgb, best_de = None, _INV_TOL
        for rgb, lab in bom_labs:
            de = ciede2000(clab, lab)
            if de <= best_de:
                best_de, best_rgb = de, rgb
        if best_rgb is not None:
            have[best_rgb] += 1
    report = {
        "#%02x%02x%02x" % rgb: {"need": need[rgb], "have": have[rgb],
                                "short": max(0, need[rgb] - have[rgb])}
        for rgb, _ in need.most_common()
    }
    totals = {"owned": len(inv), "have": sum(have.values()), "need": sum(need.values())}
    return report, totals


@app.get("/simulate")
def simulate(
    image_id: str,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    size_mm: float | None = Query(None),
    distance_m: float | None = Query(None),
    colors: int = 12,
    bare_white: bool = True,
    real_caps: bool = True,
    real_only: bool = False,
    preset: str | None = None,
    thicken: bool = False,
    dither: bool = False,
    bg_color: str = "#3c2d23",
    highlight: str | None = None,
    from_my_caps: bool = False,
    own_threshold: float = 12.0,
    unlimited_stock: bool = False,
) -> Response:
    img = _get(image_id)
    res = _solve(img, image_id, mode, pitch_mm, size_mm, distance_m)
    plan = _plan(image_id, img, res["caps_across"], colors, bare_white=bare_white,
                 preset=preset, thicken=thicken, dither=dither,
                 from_my_caps=from_my_caps, own_threshold=own_threshold,
                 unlimited_stock=unlimited_stock)
    own_mode = from_my_caps and _DB.exists()
    own_fitted = own_mode and not unlimited_stock  # small fitted piece vs full size
    if own_fitted:
        # the fitted piece drives tile sizing + physical width, not the slider
        _own_geometry(res, plan)
    # adapt tile pixels to how many caps there are, so a bigger piece shows more
    # detail while the output stays a bounded size.
    capped_across = max(1, min(res["caps_across"], _MAX_CAPS_ACROSS))
    px_per_cap = max(6, min(22, _SIM_WIDTH_PX // capped_across))
    palette = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    # Real caps are auto-cropped to their disc (see cap_crop) so every cap is the
    # same size; blend them in for photographic realism. Set real_caps=false for
    # clean procedural caps only. A plan designed FROM the owned stock must show
    # the owned caps — procedural stand-ins there would be lying.
    real_only = real_only or from_my_caps
    db = str(_DB) if ((real_caps or real_only) and _DB.exists()) else None
    lib = build_library(palette, db_path=db, size=64)
    # The gaps between round glued caps and the holes show the physical backing
    # board — one solid colour the user controls (wood/paper/paint), not the cap.
    board = _hex_rgb(bg_color, (60, 45, 35))
    hi = _hex_rgb(highlight, None) if highlight else None
    mosaic = render_mosaic_caps(plan, lib, px_per_cap=px_per_cap, background=board,
                                real_only=real_only, highlight=hi)
    if distance_m is not None and not own_fitted:
        # Shrink the sharp mosaic into a fixed FOV frame; caps merge via the
        # linear-light resample rather than a growing blur. Skipped only for the
        # FITTED caps-I-own piece: it is sized by how many caps you own (often
        # small, e.g. a few hundred caps ~ 0.4 m), so a distant view would shrink
        # it to a speck. Unlimited-stock is full-size, so distance applies as
        # usual. Showing the sharp fitted mosaic is what the builder needs.
        mosaic = view_at_distance(mosaic, res["width_mm"], distance_m, _FRAME_PX,
                                  board=_STAGE_BG)
    buf = io.BytesIO()
    mosaic.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/simplify")
def simplify(image_id: str) -> dict:
    """AI-edit the image into a cap-friendly simplified version (qwen-image-edit)
    and store it as a NEW image id — the original stays untouched. The edit
    instruction reuses the AI judge's tips for this image when available."""
    from .. import ai_edit

    img = _get(image_id)
    tips = (_LLM_CRITIQUE.get(image_id) or {}).get("tips") or []
    instructions = ai_edit.DEFAULT_INSTRUCTIONS
    if tips:
        instructions += " Specifically: " + "; ".join(tips) + "."
    try:
        out = ai_edit.ai_simplify(img, instructions)
    except Exception as exc:  # noqa: BLE001 - key/network/quota surface to UI
        raise HTTPException(502, f"AI simplify failed: {exc}") from exc
    _COUNTER["n"] += 1
    iid = str(_COUNTER["n"])
    _IMAGES[iid] = out
    return {"id": iid, "width": out.width, "height": out.height,
            "aspect": out.width / out.height}


@app.get("/palettes")
def palettes(
    image_id: str,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    size_mm: float = 1500.0,
    colors: int = 12,
    bare_white: bool = True,
    dither: bool = True,
) -> Response:
    """One sheet comparing the mosaic under each palette preset (auto/portrait/
    sunset/space), so a creator can see them side by side and pick."""
    from PIL import ImageDraw

    img = _get(image_id)
    res = _solve(img, image_id, mode, pitch_mm, size_mm, None)
    across = min(res["caps_across"], 44)  # cap resolution for a fast comparison
    board = (60, 45, 35)
    options = [("Auto", None), ("Portrait", "portrait"), ("Sunset", "sunset"), ("Space", "space")]

    thumbs = []
    for label, preset in options:
        plan = _plan(image_id, img, across, colors, bare_white=bare_white,
                     preset=preset, dither=dither)
        pal = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
        lib = build_library(pal, db_path=None, size=48)
        m = render_mosaic_caps(plan, lib, px_per_cap=8, background=board)
        thumbs.append((label, m))

    tw = 320
    resized = [(lab, m.resize((tw, max(1, round(tw * m.height / m.width))))) for lab, m in thumbs]
    th = max(r.height for _, r in resized)
    lh, cols = 26, 2
    cw, ch = tw, th + lh
    rows = (len(resized) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows * ch), (20, 22, 28))
    draw = ImageDraw.Draw(sheet)
    for i, (label, r) in enumerate(resized):
        x, y = (i % cols) * cw, (i // cols) * ch
        draw.text((x + 8, y + 5), label, fill=(230, 230, 230))
        sheet.paste(r, (x, y + lh))
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/capmap")
def capmap(
    image_id: str,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    size_mm: float | None = Query(None),
    distance_m: float | None = Query(None),
    colors: int = 12,
    bare_white: bool = True,
    preset: str | None = None,
    thicken: bool = False,
    dither: bool = False,
    format: str = "png",
) -> Response:
    """Printable paint-by-numbers cap map (PNG or PDF) for the current plan."""
    img = _get(image_id)
    res = _solve(img, image_id, mode, pitch_mm, size_mm, distance_m)
    plan = _plan(image_id, img, res["caps_across"], colors, bare_white=bare_white,
                 preset=preset, thicken=thicken, dither=dither)
    sheet = render_cap_map(plan)
    buf = io.BytesIO()
    if format.lower() == "pdf":
        sheet.save(buf, format="PDF")
        return Response(content=buf.getvalue(), media_type="application/pdf")
    sheet.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/target")
def target(
    image_id: str,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    size_mm: float | None = Query(None),
    distance_m: float | None = Query(None),
) -> Response:
    """The ORIGINAL image framed exactly like /simulate (same size/distance/frame),
    so hold-to-compare shows the target vs the cap rendering apples-to-apples."""
    img = _get(image_id).convert("RGB")
    res = _solve(img, image_id, mode, pitch_mm, size_mm, distance_m)
    if distance_m is not None:
        out = view_at_distance(img, res["width_mm"], distance_m, _FRAME_PX, board=_STAGE_BG)
    else:  # no distance -> match the sharp mosaic's canvas size
        capped = max(1, min(res["caps_across"], _MAX_CAPS_ACROSS))
        px_per_cap = max(6, min(22, _SIM_WIDTH_PX // capped))
        grid = grid_for_caps_across(capped, img.width / img.height, Cap())
        ppm = px_per_cap / pitch_mm
        out = img.resize((max(1, round(grid.width_mm * ppm)),
                          max(1, round(grid.height_mm * ppm))), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# Mounted last so the API routes above take precedence.
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
