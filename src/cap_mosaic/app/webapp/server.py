"""FastAPI backend for the Mosaic Estimator.

Endpoints:
- ``POST /upload``            -> store an image, return its id + dimensions.
- ``GET  /estimate``          -> solve size<->distance, legibility, BOM, effective colours.
- ``GET  /simulate``          -> a cap-rendered mosaic (PNG), optionally blurred for distance.
"""

from __future__ import annotations

import io
from collections import Counter
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from ...core import estimator
from ...core.geometry import Cap, grid_for_caps_across
from ...core.sizing import apparent_fraction
from ...core.palette import preset_palette
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
          dither: bool = False):
    caps_across = max(1, min(caps_across, _MAX_CAPS_ACROSS))
    key = (image_id, caps_across, colors, bare_white, preset, thicken, dither)
    if key not in _PLANS:
        grid = grid_for_caps_across(caps_across, img.width / img.height, Cap())
        pal = preset_palette(preset) if preset else None
        if pal is not None:  # a curated palette overrides k-means colour derivation
            _PLANS[key] = plan_from_image(img, grid, palette=pal, bare_white=bare_white,
                                          thicken_outlines=thicken, dither=dither)
        else:
            _PLANS[key] = plan_from_image(img, grid, colors=colors, bare_white=bare_white,
                                          thicken_outlines=thicken, dither=dither)
    return _PLANS[key]


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
                 preset=preset, thicken=thicken, dither=dither)
    counts = Counter(tuple(c.rgb) for c in plan.cells if not c.is_hole)
    palette = list(counts.keys())
    view_d = res.get("distance_m") or res.get("recommended_distance_m") or 5.0

    # Report caps you actually buy: the area estimate counts the whole panel, but
    # a removed/bare-white background leaves holes with no cap. total_caps is the
    # real (background-excluded) count; panel_caps keeps the full-panel figure.
    res["panel_caps"] = res["total_caps"]
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
    return res


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
) -> Response:
    img = _get(image_id)
    res = _solve(img, image_id, mode, pitch_mm, size_mm, distance_m)
    plan = _plan(image_id, img, res["caps_across"], colors, bare_white=bare_white,
                 preset=preset, thicken=thicken, dither=dither)
    # adapt tile pixels to how many caps there are, so a bigger piece shows more
    # detail while the output stays a bounded size.
    capped_across = max(1, min(res["caps_across"], _MAX_CAPS_ACROSS))
    px_per_cap = max(6, min(22, _SIM_WIDTH_PX // capped_across))
    palette = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    # Real caps are auto-cropped to their disc (see cap_crop) so every cap is the
    # same size; blend them in for photographic realism. Set real_caps=false for
    # clean procedural caps only.
    db = str(_DB) if ((real_caps or real_only) and _DB.exists()) else None
    lib = build_library(palette, db_path=db, size=64)
    # The gaps between round glued caps and the holes show the physical backing
    # board — one solid colour the user controls (wood/paper/paint), not the cap.
    board = _hex_rgb(bg_color, (60, 45, 35))
    hi = _hex_rgb(highlight, None) if highlight else None
    mosaic = render_mosaic_caps(plan, lib, px_per_cap=px_per_cap, background=board,
                                real_only=real_only, highlight=hi)
    if distance_m is not None:
        # Shrink the sharp mosaic into a fixed FOV frame; caps merge via the
        # linear-light resample rather than a growing blur.
        mosaic = view_at_distance(mosaic, res["width_mm"], distance_m, _FRAME_PX)
    buf = io.BytesIO()
    mosaic.save(buf, format="PNG")
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
        out = view_at_distance(img, res["width_mm"], distance_m, _FRAME_PX)
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
