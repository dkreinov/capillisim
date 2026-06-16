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
- **Designer:** supports both simple patterns and photo/portrait mosaics, with a
  viewing-distance simulator to guide the trade-off.
- **Stack:** Python + OpenCV.

## Docs

- `docs/PRIOR_ART.md` — what exists, what's novel.
- `docs/ARCHITECTURE.md` — components, data flow, the portable-core split, math.
- `docs/POC_OPERATION.md` — how projector + phone + PC connect and run the loop.
- `docs/HARDWARE.md` — the physical rig and the specs we still need.
- `docs/ROADMAP.md` — phased scope, milestones, and the POC success criteria.
