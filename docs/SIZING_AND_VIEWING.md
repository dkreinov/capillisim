# Sizing & Viewing: how big, how many caps, how far to stand

This guide turns the projector geometry and the human eye into concrete numbers:
what physical size a piece will be, how many caps it needs, how detailed it will
look, and the distance to view it from. Numbers below assume the rig projector
(MAGCUBIC HY320 NTV: **throw ratio 1.10:1**, native 1920×1080, 500 ANSI, minimum
focus ~0.7 m) and a **32 mm cap pitch**. Re-run `app/sizing.py` for other values.

## Two independent factors

A finished piece is decided by two things that don't affect each other:

1. **Geometry — the projector.** A fixed-throw projector mounted height **H**
   above the table paints an image of width **W = H ÷ throw_ratio** (16:9, so the
   table depth is W × 9/16). With cap pitch **p**, that's **W ÷ p caps across**.
   Because focus has a minimum (~0.7 m), the *smallest sharp image is ~64 cm
   wide* — your piece can't be tiny.

2. **Perception — the eye.** Physical size does **not** change perceived detail;
   it only sets how far back you stand. A cap of pitch *p* viewed at distance *d*
   subtends an angle `p / d`.

## The key law: detail = caps across, not size

Caps-across is the real "resolution" of the piece, exactly like pixels across an
image. A bigger piece with the same caps-across is *not* more detailed — you just
view it from further away, and it looks identical. So:

- Choose **caps-across** for the detail you want.
- The projector throw then fixes the **physical size** (= caps-across × pitch).
- You then stand at the distance where the piece fills a comfortable field of
  view.

Rough detail guide (caps across): **~15–20** = bold shapes, logos, text read;
**~25–35** = a recognisable face / simple portrait; **~50+** = photo-ish;
**~80+** = fine detail. This projector tops out around **45 across** before the
piece gets large and dim, so favour **bold, high-contrast subjects**.

## Geometry table (throw 1.10, 32 mm caps, 16:9)

| Mount height | Image W | Depth | Caps across | Caps down | ~Total caps | View @40° | View @15° |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.70 m | 64 cm | 36 cm | 19 | 11 | ~210 | 0.9 m | 2.4 m |
| 0.90 m | 82 cm | 46 cm | 25 | 14 | ~350 | 1.1 m | 3.1 m |
| 1.10 m | 100 cm | 56 cm | 31 | 17 | ~530 | 1.4 m | 3.8 m |
| 1.30 m | 118 cm | 66 cm | 36 | 20 | ~720 | 1.6 m | 4.5 m |
| 1.60 m | 145 cm | 82 cm | 45 | 25 | ~1125 | 2.0 m | 5.5 m |

"View @40°/@15°" is the distance at which the whole width fills that horizontal
field of view — 40° is an immersive close look, 15° sees it as a single picture.

## Viewing distance & the pointillism effect

Individual caps stay visible up close and only become physically unresolvable
very far away (a 32 mm cap subtends 1 arc-minute — the eye's limit — at ~110 m).
You don't need them to vanish. A *picture* made of caps "reads" once each cap
subtends roughly **20–30 arc-minutes**, because the brain integrates coarse tiles
into an image. For 32 mm caps:

- **Reads as a picture** from about **4 m** out.
- **Essentially smooth** tiles only beyond ~35 m (not practical — and not needed).

So in practice: build it, then step back to **~3–5 m** for a ~0.7–1.0 m piece —
far enough that the tiles blend, close enough to see the whole thing. Bigger
pieces are viewed proportionally further back.

## Worked examples (this projector)

- **Small test piece (recommended first build).** Mount ~0.80 m → ~73 × 41 cm,
  ~22 across × 12 down, ~210–260 caps (landscape subject). Brightest, fewest
  caps, easiest mount; a bold face/logo reads from ~3 m. Great for proving the
  whole loop.
- **Medium piece.** Mount ~1.1 m → ~100 × 56 cm, 31 across, ~530 caps. Clearly
  better detail; needs a darker room and a real cap-collecting effort.
- **Big piece.** Mount ~1.5 m+ → 140 cm+, 45+ across, 1000+ caps. Most
  photo-like, but a tall mount, big table, dim image, and a lot of caps.

Note the throw is **16:9**: a *square* piece only uses the middle of the beam, so
a square N×N needs the projector higher than a landscape N-across piece. Pick
landscape subjects to use the projector efficiently, or mount higher for square.

## Brightness

500 ANSI lumens lights a ~64–100 cm image fine in a **dim** room; it washes out
in bright light. The green target ring is high-contrast and shows through modest
ambient light, but build in subdued lighting. Always read a cap's colour
**outside** the projector beam (or blank the projection briefly) so projected
light doesn't tint the measured colour. Bright ambient light is only a problem
while *building*; the finished, glued piece is viewed in normal light.

## Recompute for your setup

```bash
PYTHONPATH=src python -m cap_mosaic.app.sizing --throw 1.10 --pitch 32 \
    --heights 0.7 0.9 1.1 1.3 1.6
```

Then size a plan to match with the designer, e.g. 22 caps across:

```bash
PYTHONPATH=src python -m cap_mosaic.app.cli design --image yourpic.jpg \
    --caps-across 22 --cap-diameter 32 --out plans/piece.capproj.json \
    --preview-dir previews --distances 1 3 6
```

The `--preview-dir` distance images show exactly how your subject will read as it
blends — check them before committing to a cap count.
