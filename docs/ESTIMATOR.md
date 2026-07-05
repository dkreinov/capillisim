# Mosaic Estimator (web app)

Date: 2026-07-01. Code: `src/cap_mosaic/app/webapp/`, `core/estimator.py`,
`core/legibility.py`, `app/cap_render.py`, `app/fake_caps.py`.

A local web app to answer, for any image: **how big must the mosaic be, from how
far is it seen well, and how many caps of each colour does it take**, with a
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

- **Legibility floor** (`core/legibility.py`): render the image at N caps-across
  and compare structure to the original (windowed SSIM); the smallest N that
  clears a threshold is the minimum caps to represent the subject. Below it the
  app warns: *won't read from any distance*. Detailed images need many more caps
  than simple ones; **Pattern** mode uses a looser threshold (no subject to
  recognise).
- **Size ↔ distance** (`core/estimator.py`):
  - *size → distance*: caps-across from the width; the **min distance** where
    caps stop being visible (they blend) and the **recommended** distance that
    fills a comfortable field of view;
  - *distance → size*: the width that fills the view at that distance, flagged if
    it falls below the legibility floor.
- **Shades merge with distance**: far away, near colours blend, so the effective
  palette shrinks (`effective_colors`); the app shows *colours used / seen*.
- **Realistic simulation** (`app/cap_render.py`, `app/fake_caps.py`,
  `planner_designer.view_at_distance`, `core/sizing.py`): the mosaic is tiled
  from actual cap images (real `dataset/caps.db` crops + procedurally generated
  fake caps with rims/logos). To show a viewing distance it is **not** blurred:
  it **shrinks inside a fixed field of view frame and stays sharp**. As it
  subtends fewer pixels, an area-resample done in **linear light** (sRGB→linear→
  area-average→sRGB) merges neighbouring caps; that is physically-correct
  optical colour mixing, so a 50/50 black+white tile averages to the linear
  midpoint (~188), not the sRGB midpoint (~128). `apparent_fraction(width,
  distance, fov)` sets how much of the ~50° frame the piece fills (shown as
  *fills ~X% of your view*). **Close up it fills your view as caps; far away it
  is a small sharp picture in bare board.**
- **Bare-white background**: cells sampled as near-white (all channels ≥
  `white_level`, default 238) are left as **bare board** (holes), not paved with
  white caps. Controlled by `plan_from_image(bare_white=...)`; on by default in
  the app, overridable with `&bare_white=false`.
- **Dither**: with `dither=true` (default on in the UI), non-hole cell colours
  come from CIELAB Floyd–Steinberg error diffusion (`core/dither.py`) instead of
  independent nearest-colour. A small palette then reproduces gradients/tones via
  a blend the eye merges at distance, rather than banding. See docs/RESEARCH.md.
- **Hold-to-compare (A/B)**: the `👁 hold to compare` button swaps the cap sim
  for the *original* image framed identically (`/target`), so you can judge how
  faithfully the caps read at the chosen size/distance.
- **Printable cap map**: `⬇ Cap map (PDF)` downloads a paint-by-numbers sheet
  (`app/cap_map.py`): a letter per colour on each cell, row/col rulers, and a
  legend (letter · hex · count). The artifact you actually build from.
- **Inventory gap**: `Shopping list (have / short per colour)` (in the "My
  scanned caps" group) matches your scanned `caps.db` against the
  BOM (greedy nearest, CIEDE2000 ≤ 12) and shows *have · short* per colour plus
  *you own X of Y needed*. Report only; the plan is not constrained by stock.
- **Cap-art check + AI judge**: every upload gets a heuristic score (contrast,
  detail floor, background simplicity) with tips and `✨ Apply suggestions`.
  `🧠 AI judge` (Qwen `qwen3-vl-plus`, needs `QWEEN_KEY`) adds an AI verdict.
  `🪄 AI fix` goes further: the judge returns **whitelisted actions** (colors
  4–24, thicken, dither, size_m, preset; nothing else is accepted) which are
  auto-applied to the controls, with a *before* snapshot kept next to the new
  simulation for comparison.
- **AI simplify**: `🎨 AI simplify` (qwen-image-edit-plus) edits the image
  itself into a cap-friendly version (≤6 flat colours, thickened lines, clutter
  removed, same subject) using the judge's own tips as the edit instruction.
  Stored as a NEW image in the **version strip** (Original · crops · AI edits;
  click to switch, ⬇ to save any version). Opt-in per click.

## Endpoints

- `POST /upload`: image -> `{id, width, height, aspect}`
- `GET /estimate?image_id=&size_mm=|distance_m=&mode=&colors=&bare_white=&preset=&thicken=&dither=&inventory=`
  -> caps, legibility, distances, `bom` (hex -> count), colours used/effective,
  `apparent_pct`, and (with `inventory=true`) `inventory` + `inventory_totals`
- `GET /simulate?...&bg_color=&real_caps=&real_only=&preset=&thicken=&dither=&highlight=`
  -> cap-rendered PNG of the fixed FOV frame: the sharp mosaic shrunk to the size
  it subtends at the distance, on the chosen board colour
- `GET /target?image_id=&size_mm=&distance_m=&mode=` -> the ORIGINAL image framed
  exactly like `/simulate` (for hold-to-compare)
- `GET /capmap?image_id=&...&format=pdf|png` -> printable paint-by-numbers cap map
- `GET /crop?image_id=&x0=&y0=&x1=&y1=` / `GET /image?image_id=` -> region crop + preview
- `GET /critique?image_id=&llm=` -> heuristic score/tips/recommendations; with
  `llm=true` also the Qwen verdict incl. whitelisted `actions`
- `GET /simplify?image_id=` -> AI-edited (simplified) copy stored as a new id
- `GET /palettes?image_id=&size_mm=` -> side-by-side preset comparison sheet
- `GET /inventory` -> the cap-inventory browser page; `GET /inventory/caps`
  (JSON, newest first), `GET /inventory/crop/{id}` (thumbnail),
  `DELETE /inventory/caps/{id}` (removes the row AND its crop files). Linked
  from the "My scanned caps" group: browse every scanned cap (photo,
  field|mosaic swatch bar, mm + S/L class, size filters) and delete a mis-scan
  with the mouse — click ×, then `delete?`; clicking anywhere else cancels.
- `GET /inventory/test/{id}?distance_m=&across=&bg=` -> the believe-your-eyes
  colour test (click any cap in the browser): LEFT half of a patch is the
  cap's real photo tiled, RIGHT half is the solid mosaic colour the planner
  stores for it. The patch stays FULL-SIZE on screen; as `distance_m` grows,
  each cap's logo/text washes out in linear light (a 3 cm cap stays resolved
  as a disc until absurd distances — what actually merges at a few metres is
  its internal detail), so the cap reads as its flat average. If the tiled
  half melts into the solid block, the stored mosaic colour is what the eye
  gets from that cap in a wall. Cap tiles are cut GEOMETRY-DRIVEN
  (`cap_crop.cap_circle` with the cap's known class size over the crop span):
  centre from the distance-transform peak or narrow-band Hough (white caps are
  invisible to thresholds), radius from the steepest radial-brightness step
  under a size prior — so tiles meet at the metal edge like really glued caps.

The inventory browser and the colour test:

![the cap inventory browser: hundreds of scanned caps in a grid](images/inventory-browser.png)

![colour test: a navy cap tiled beside its grey-blue at-distance colour, blending as they shrink](images/colour-test.png)

## Building from caps (projector)

Once you have a `.capproj.json` plan, `app/project_plan.py` projects it onto the
board (`procam/render.render_stencil`): **S** lights every cell in its cap colour
(a 1:1 stencil: drop each cap on its disc); **C** / **N** / **P** light one
colour at a time so you glue a whole colour before moving on; **Q** quits. Display
and keys are injected callables (headless-tested); `main` drives the real
fullscreen projector. On-rig calibration + verification is still pending.

## Limitations / next

- SSIM legibility threshold is a heuristic (exposed for calibration on real
  images). Pattern/picture is a manual toggle; recognition comes later.
- Online cap datasets (Kaggle, images.cv) are deferred: they need auth +
  licensing review; the POC uses procedural + captured caps.
- Plan/BOM resolution is capped (`_MAX_CAPS_ACROSS`) to keep the UI responsive.

## Known gaps

The distance model captures shrink + optical (acuity-bounded) blending in linear
light. Left for later:

- **Contrast sensitivity (CSF).** Real acuity depends on contrast, not just
  angular size; a full model would fold in the contrast-sensitivity function.
  We use a fixed acuity (`ACUITY_ARCMIN ≈ 1.5`) as the optical limit.
- **`read_quality` vs optical acuity.** `read_quality` is a coarse
  *perceptual-integration* heuristic (when the brain fuses tiles into a subject),
  a different thing from the optical area-resample; the two are not yet unified.
- **White subject vs white background.** Bare-white holing can't tell a white
  *subject* from a white *background*; it drops both. A subject/background
  segmentation would disambiguate.
- **Gloss & lighting.** Cap gloss, specular highlights, and ambient lighting are
  out of scope; the simulation assumes flat, evenly-lit matte tiles.
