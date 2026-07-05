# Capillisim

*cap + pointillism.* Build a wall-sized mosaic out of bottle caps, guided by
software: design the artwork from any image, scan the caps you collect, and let
a projector show you where every cap goes.

A cap is one fat pixel of about 32 mm. Up close you see caps; from a few metres
the eye blends them into a picture. Everything in this repo serves that trick.

![generate, AI simplify, caps up close, reads from afar](docs/images/pipeline-lion.jpg)

## Quickstart

```bash
pip install -e .[web]

# the designer web app
PYTHONPATH=src python -m cap_mosaic.app.webapp        # http://127.0.0.1:8000

# the cap scanner (print the reading card first: python -m cap_mosaic.app.make_card)
PYTHONPATH=src python -m cap_mosaic.app.cap_capture --out dataset --auto
```

Full illustrated walkthrough: **[docs/GUIDE.md](docs/GUIDE.md)**.

## 1. Design the artwork

Drop, paste, or generate any image. The estimator turns it into a buildable cap
plan: trade off physical size against viewing distance, and watch a perceptually
honest simulation (the mosaic shrinks and stays sharp with distance, colours mix
in linear light, no fake blur).

![the estimator: judge, versions, simulation, BOM](docs/images/app-ui.jpg)

- **Judges.** A heuristic check scores every image for cap-art suitability
  (contrast, detail floor, background). A Qwen vision judge adds taste on
  demand: `🪄 AI fix` applies its recommended settings, `🎨 AI simplify`
  redraws the image itself into flat, thick-lined, cap-friendly art:

  ![before and after AI simplify](docs/images/ai-simplify.jpg)
- **Versions.** Original, crops, and AI edits live in a version strip: click to
  switch, save any of them.
- **Build artifacts.** A printable paint-by-numbers cap map (PDF), and a
  per-colour bill of materials with have/short counts from your scanned caps:

  ![paint-by-numbers cap map](docs/images/capmap-sample.png)

## 2. Scan your caps

Place a cap on the printed reading card. The scanner locates the card,
colour-corrects, reads the cap, measures its true size in mm, and auto-saves
when the reading is stable; a hand in frame or glare gets rejected and retried.
Here a 37 mm large cap (note the LARGE CAP badge and size line) followed by a
standard crown, with the last-scans strip updating below:

![live cap scanning: a large cap and a standard cap recognised, sized and saved](docs/images/cap-scan-demo.gif)

Each cap is stored with two colours: the *field* colour (recognises the cap in
hand) and the *mosaic* colour (the linear-light mix of the whole face, logo
included, which is what the cap contributes to the picture from a distance and
what the planner matches on):

![field vs mosaic colour of real caps](docs/images/field-vs-mosaic.png)

The scanner also computes a rotation-invariant ring signature, so it recognises
a cap it has seen before and the inventory can be browsed by similarity:

![caps ranked by similarity to a query cap](docs/images/similar-caps.png)

Cap size is measured automatically off the card's mm-true geometry (standard
crowns vs 38 mm large caps), so the inventory knows which caps fit which artwork:

![automatic size measurement of a large cap](docs/images/cap-size-measure.png)

Every scanned cap lands in a browsable inventory (http://127.0.0.1:8000/inventory)
— photo, field|mosaic swatch bar, measured size — where you can filter by size
and delete a mis-scan with the mouse:

![the cap inventory browser: hundreds of scanned caps in a grid](docs/images/inventory-browser.png)

Click any cap for the believe-your-eyes colour test: your cap's real photo
tiled next to the solid *mosaic* colour the planner will use, both shrinking
with a distance slider under physically-correct linear-light mixing. If the
seam vanishes as you step back, the planner's colour is what your eye actually
gets. Here a cap that looks deep **navy** in hand reads **grey-blue** at
distance, because its white logo mixes in — exactly the field-vs-mosaic split:

![colour test: a navy cap tiled beside its grey-blue at-distance colour, blending as they shrink](docs/images/colour-test.png)

## 3. Build it

Two projector modes place the caps on the board at true 1:1 scale
(`python -m cap_mosaic.app.project_plan`): a full colour **stencil** where you
drop each cap on the disc lit in its colour, and a **one colour at a time** pass
like muralists work. The interactive loop goes further: hold any random cap up
to the camera, the software matches it to the best empty cell (or says set it
aside), and the projector glows on that exact cell. State persists between
sessions; caps stay removable until the final glue-down.

## Prior art

Mosaic generation itself is well covered by existing tools (photomosaic
generators, bead-pattern apps, academic bottle-cap-art papers). This project's
focus is the part those tools stop short of: the camera-plus-projector loop
that guides the physical placement of each cap. Survey in `docs/PRIOR_ART.md`.

## Design decisions

- **Compute:** PC + phone for the proof of concept (the laptop drives the
  projector and logic, the phone streams its camera). The core logic is
  isolated so it can move to phone-only later.
- **Caps:** open-ended random supply; matching tolerates "no good slot, set it
  aside."
- **Recognition:** dominant colour for the POC; brand/logo ID architected but
  deferred.
- **Stack:** Python + OpenCV.

## Docs

- `docs/GUIDE.md`: **start here as a user.** The illustrated guide: design, judge, simulate, print, project, build.
- `docs/RIG_SETUP.md`: **start here for the physical build.** Boxes, calibration, live loop, with diagrams.
- `docs/ESTIMATOR.md`: the web app's model and endpoint reference.
- `docs/ARCHITECTURE.md`: components, data flow, the portable-core split.
- `docs/CALIBRATION.md`: the projector-to-table calibration procedure.
- `docs/POC_OPERATION.md`: how projector, phone, and PC connect and run the loop.
- `docs/SIZING_AND_VIEWING.md`: piece size, cap count, viewing distance.
- `docs/COLOR_MATCHING.md`: perceptual ΔE matching and the place-or-leave-empty threshold.
- `docs/DATA_MODEL.md`: the SQLite cap inventory schema.
- `docs/HARDWARE.md`: the rig and the specs still needed.
- `docs/ROADMAP.md`: milestones and POC success criteria.
- `docs/PRIOR_ART.md`: what exists, what's novel.
- `docs/RESEARCH.md`: cap datasets to import and techniques to adopt.
- `docs/HANDOFF.md`: current state, built vs pending. Start here to resume work.
