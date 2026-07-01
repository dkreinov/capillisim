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
from ..cap_render import build_library, render_mosaic_caps
from ..planner_designer import plan_from_image, simulate_distance

app = FastAPI(title="Capillisim Mosaic Estimator")

_IMAGES: dict[str, Image.Image] = {}
_COUNTER = {"n": 0}
# Use the captured cap dataset for realistic caps + BOM when it exists.
_DB = Path("dataset/caps.db")
_MAX_CAPS_ACROSS = 140  # render resolution ceiling; bigger size -> more detail
_SIM_WIDTH_PX = 1200  # target simulation width; tile px adapts to keep it bounded


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


def _get(image_id: str) -> Image.Image:
    img = _IMAGES.get(image_id)
    if img is None:
        raise HTTPException(404, "unknown image id (upload first)")
    return img


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


def _plan(image_id: str, img: Image.Image, caps_across: int, colors: int):
    caps_across = max(1, min(caps_across, _MAX_CAPS_ACROSS))
    key = (image_id, caps_across, colors)
    if key not in _PLANS:
        grid = grid_for_caps_across(caps_across, img.width / img.height, Cap())
        _PLANS[key] = plan_from_image(img, grid, colors=colors)
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

    plan = _plan(image_id, img, res["caps_across"], colors)
    counts = Counter(tuple(c.rgb) for c in plan.cells if not c.is_hole)
    palette = list(counts.keys())
    view_d = res.get("distance_m") or res.get("recommended_distance_m") or 5.0

    res["bom"] = {"#%02x%02x%02x" % rgb: n for rgb, n in counts.most_common()}
    res["colors_used"] = len(palette)
    res["effective_colors"] = len(estimator.effective_colors(palette, view_d, pitch_mm))
    return res


@app.get("/simulate")
def simulate(
    image_id: str,
    mode: str = "picture",
    pitch_mm: float = 32.0,
    size_mm: float | None = Query(None),
    distance_m: float | None = Query(None),
    colors: int = 12,
) -> Response:
    img = _get(image_id)
    res = _solve(img, image_id, mode, pitch_mm, size_mm, distance_m)
    plan = _plan(image_id, img, res["caps_across"], colors)
    # adapt tile pixels to how many caps there are, so a bigger piece shows more
    # detail while the output stays a bounded size.
    capped_across = max(1, min(res["caps_across"], _MAX_CAPS_ACROSS))
    px_per_cap = max(6, min(22, _SIM_WIDTH_PX // capped_across))
    palette = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    lib = build_library(palette, db_path=str(_DB) if _DB.exists() else None, size=64)
    mosaic = render_mosaic_caps(plan, lib, px_per_cap=px_per_cap)
    if distance_m is not None:
        mosaic = simulate_distance(mosaic, px_per_mm=px_per_cap / pitch_mm,
                                   distance_m=distance_m)
    buf = io.BytesIO()
    mosaic.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# Mounted last so the API routes above take precedence.
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
