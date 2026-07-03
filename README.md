# Capillisim

*cap + pointillism* — because building a picture from discrete colored caps is
exactly what the pointillists did with dots.

Interactively build a mosaic out of bottle caps (mostly beer caps), guided by a
projector and a phone camera. You design a target image, the system computes the
cap layout at true real-world scale, and then — as you pick up each random cap —
it tells you the best empty slot (or that the cap doesn't help) and the projector
lights up that exact cell so you just drop the cap in place. The build happens in
stages over time; state persists between sessions.

This is a fresh project, independent of the personal-wiki repo it was sketched
in. See `docs/` for the full design.

## Why this might be original

The mosaic-*generation* problem is well-solved (academic "structure-aware bottle
cap art", open-source generators, bead/cross-stitch tools). What does **not**
exist as a product is the interactive build loop: show an *arbitrary* cap to a
camera, have software match it to the best remaining slot or reject it, and have
a projector highlight that slot at 1:1 scale. That integration is the point of
this project. Details in `docs/PRIOR_ART.md`.

## Design decisions (locked)

- **Compute:** PC + phone for the POC (laptop drives projector + runs logic;
  phone streams its camera). Phone-only is a later goal, so the core logic is
  isolated for reuse.
- **Surface:** flat table, projector and phone looking straight down; caps
  removable until the final glue-down.
- **Caps:** open-ended / random supply. Matching tolerates "unknown cap, closest
  slot, or set aside."
- **Recognition:** dominant color for the POC; brand/logo ID architected but
  deferred.
- **Two colours per cap:** the *field* colour recognises a cap in hand; the
  *mosaic* colour — the linear-light mix of the whole face, logo included — is
  what the cap contributes to the picture from viewing distance, and is what
  the planner matches on. Real scanned caps:

  ![field vs mosaic colour of real caps](docs/images/field-vs-mosaic.png)
- **Designer:** supports both simple patterns and photo/portrait mosaics, with a
  viewing-distance simulator to guide the trade-off.
- **Stack:** Python + OpenCV.

## Docs

- `docs/RIG_SETUP.md` — **start here for the build:** boxes → calibration → live loop, with diagrams.
- `docs/PRIOR_ART.md` — what exists, what's novel.
- `docs/ARCHITECTURE.md` — components, data flow, the portable-core split, math.
- `docs/POC_OPERATION.md` — how projector + phone + PC connect and run the loop.
- `docs/CALIBRATION.md` — the projector→table calibration procedure (step by step).
- `docs/SIZING_AND_VIEWING.md` — piece size, cap count, and viewing distance.
- `docs/ESTIMATOR.md` — the web app: drag an image, trade off size ↔ distance, see the caps-vs-picture simulation and per-colour BOM.
- `docs/COLOR_MATCHING.md` — perceptual ΔE matching and the place-or-leave-empty threshold: research, anchors, calibration plan.
- `docs/DATA_MODEL.md` — the SQLite cap dataset/inventory schema (caps + crops + quality + busy-ness + future embeddings).
- `docs/HARDWARE.md` — the physical rig and the specs we still need.
- `docs/ROADMAP.md` — phased scope, milestones, and the POC success criteria.
- `docs/RESEARCH.md` — cap-image datasets to import and photomosaic/build techniques to adopt.
- `docs/HANDOFF.md` — current state + what's built vs pending (start here to resume).
