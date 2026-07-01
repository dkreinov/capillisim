# Mosaic Estimator (web app)

Date: 2026-07-01. Code: `src/cap_mosaic/app/webapp/`, `core/estimator.py`,
`core/legibility.py`, `app/cap_render.py`, `app/fake_caps.py`.

A local web app to answer, for any image: **how big must the mosaic be, from how
far is it seen well, and how many caps of each colour does it take** — with a
realistic simulation of how it reads at a chosen size and distance.

## Run

```bash
pip install -e .[web]                      # fastapi, uvicorn, python-multipart
PYTHONPATH=src python -m cap_mosaic.app.webapp     # http://127.0.0.1:8000
```

Drag an image in, pick **Picture** or **Pattern**, then move the **size** and
**viewing-distance** sliders. Buttons solve one axis from the other ("size for
this distance" / "distance for this size").

## The model

Caps are a fixed physical size (~32 mm), so a mosaic is a heavy downsampling of
the target and only reads once you stand far enough that caps blend.

- **Legibility floor** (`core/legibility.py`) — render the image at N caps-across
  and compare structure to the original (windowed SSIM); the smallest N that
  clears a threshold is the minimum caps to represent the subject. Below it the
  app warns: *won't read from any distance*. Detailed images need many more caps
  than simple ones; **Pattern** mode uses a looser threshold (no subject to
  recognise).
- **Size ↔ distance** (`core/estimator.py`) —
  - *size → distance*: caps-across from the width; the **min distance** where
    caps stop being visible (they blend) and the **recommended** distance that
    fills a comfortable field of view;
  - *distance → size*: the width that fills the view at that distance, flagged if
    it falls below the legibility floor.
- **Shades merge with distance** — far away, near colours blend, so the effective
  palette shrinks (`effective_colors`); the app shows *colours used / seen*.
- **Realistic simulation** (`app/cap_render.py`, `app/fake_caps.py`) — the mosaic
  is tiled from actual cap images (real `dataset/caps.db` crops + procedurally
  generated fake caps with rims/logos), then blurred for the viewing distance:
  **close up you see caps, far away you see the picture**.

## Endpoints

- `POST /upload` — image -> `{id, width, height, aspect}`
- `GET /estimate?image_id=&size_mm=|distance_m=&mode=&colors=` -> caps, legibility,
  distances, `bom` (hex -> count), colours used/effective
- `GET /simulate?image_id=&size_mm=&distance_m=&mode=` -> cap-rendered PNG, blurred
  for the distance

## Limitations / next

- SSIM legibility threshold is a heuristic (exposed for calibration on real
  images). Pattern/picture is a manual toggle; recognition comes later.
- Online cap datasets (Kaggle, images.cv) are deferred — they need auth +
  licensing review; the POC uses procedural + captured caps.
- Plan/BOM resolution is capped (`_MAX_CAPS_ACROSS`) to keep the UI responsive.
