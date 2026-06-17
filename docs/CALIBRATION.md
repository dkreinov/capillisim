# Calibration (projector → table)

Calibration is the one spatial setup step the POC needs. It lets the software
light up a glowing ring at the *correct real-world spot and size* on the table,
so the cap you're holding goes exactly where the projector tells you.

## Why it's needed

The projector hangs above the table but is never perfectly centred or
perpendicular. A rectangle it projects lands as a **keystoned** (skewed)
quadrilateral, at an unknown position and scale. Calibration measures that
distortion once and inverts it.

Concretely it finds a **homography** — a 3×3 projective transform that maps
*table millimetres → projector pixels*. Four point correspondences fully
determine it (position, scale, rotation, and keystone = 8 numbers). The math is
in `procam/calibrate.py`; this doc is the operator procedure.

## What you need

- Projector mounted above the table, pointing straight down, **not moving**.
- PC connected to the projector by **HDMI**, display set to **Extend** (the
  projector is a second monitor).
- A **tape measure** and a **ruler**.
- `pip install opencv-python` (only the projector display needs it).

## Find the projector's monitor X offset

The fullscreen window must land on the projector, not the laptop. On Windows the
extended display sits at a virtual-desktop X equal to the primary screen's width
(e.g. a 1920-wide laptop with the projector to its right → X = 1920). Pass that
as `--display-x`. If unsure, try `0` and your primary width; the markers appear
on whichever screen is correct.

## Procedure

1. Decide a **table origin** and axes. Tape a corner of your working rectangle:
   that corner is (0, 0). **+x to the right, +y away from you**, in millimetres.
   (Use this same frame as the piece you'll build — see "Orientation" below.)

2. Run:

   ```bash
   PYTHONPATH=src python -m cap_mosaic.app.calibrate \
       --out calibration/table.json --display-x 1920
   ```

3. Four numbered green crosshairs appear on the table (corners, inset 12%).

4. For each marker **1→4**, measure the distance of its **centre** from your
   origin and type `x y` (mm) in the terminal, e.g. `120 80`.

5. It solves and saves `calibration/table.json`.

6. **Verify 1:1:** it then projects a rectangle plus a **100 mm yellow bar**.
   Measure the bar with a ruler. If it reads 100 mm (±~1–2 mm), scale is true.
   If it's off, the markers were mis-measured — rerun and re-measure carefully.
   Press a key in the projector window to finish.

## Orientation (first-light gotcha)

A plan's cell coordinates run from (0,0) at the top-left of the frame, x right,
y down the image. When projected from above, "y down the image" must line up
with the table axis you measured as +y. If the first projected piece comes out
**mirrored or rotated**, you have an axis mismatch: either rotate the physical
board 180°, or redo calibration with +y pointing the other way. Decide the board
orientation once and keep it.

## Re-running

Calibration is per physical setup. If the projector, its mount, or the table
move at all, **recalibrate** before building (it takes about a minute). If
nothing moved between sessions, the saved `table.json` is still valid — just load
it. A good habit is to recalibrate at the start of each session anyway.

## Output

`calibration/table.json` holds the homography plus the projector pixel
dimensions. `app/run_build.py` loads it with `--calibration calibration/table.json`.
Calibration files are git-ignored (they're specific to your rig).
