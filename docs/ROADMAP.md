# Scope & Roadmap

## POC success criteria (the target)

On a small area (about a 10×10 cell region), with the projector calibrated to
true 1:1 scale, I can:

1. Hold up a series of random caps to the phone.
2. For each cap, within a couple of seconds, the system either **highlights the
   correct empty cell** (matched by color) so I can drop the cap in, or tells me
   to **set the cap aside** because it doesn't help this piece.
3. Confirm placement (a keypress for the POC) and have the cell marked filled.
4. Stop and resume later with state intact.

Matching is driven by **color** for the POC. Brand/logo ID is deferred (see
Milestone 4) and is not required for success.

## Milestones

### M0 — Project setup *(done)*
Repo, prior-art review, architecture/hardware/scope docs, package skeleton.

### M1 — Designer core (no hardware, fully testable) *(done)*
Pure-Python `core/`: hex-grid layout, palette quantization, image → `GridPlan`,
bill-of-materials, the viewing-distance simulator, and the JSON project-file
format. **Deliverable:** a CLI that turns an image + size/cap-count into a plan,
a per-color BOM, and "view from X metres" preview PNGs.

### M2 — Projection + calibration *(core done; on-rig display pending)*
4-corner / known-rectangle calibration to recover 1:1 scale + keystone
(homography between table mm and projector px); render the full template and a
single glowing highlighted cell at the correct table position. The homography
math and frame rendering are implemented and unit-tested headless; putting the
frame fullscreen on the real projector is the remaining hardware step.
**Deliverable:** project a plan at true size and light up any chosen cell.

### M3 — The interactive loop (this is the POC) *(logic done; phone capture pending)*
Phone MJPEG stream → detect cap → read color (glare-robust) → match to best empty
cell or reject → highlight → manual confirm → persist. Wire M1 + M2 + vision
together. The matcher, the glare-robust color reader, and the full loop are
implemented and tested headless (run_loop with injected I/O); a narrated
simulation places and rejects synthetic caps end to end. Remaining: grab frames
from a real phone stream (OpenCV), put the projector frame fullscreen, and tune
the reject threshold against real caps. **Deliverable:** the full small-grid
loop meeting the success criteria above. See `docs/POC_OPERATION.md`.

### M4 — Enhancements
- Brand/logo recognition (the deferred request): a classifier + cap dataset;
  lets designs target specific caps and refines matches.
- Auto-verify placement via a phone↔table homography (no manual confirm).
- Scarcity-aware matching so rare colors aren't wasted.
- Inventory capture: photograph your cap pile to estimate what palette you have.

### M5 — Phone-only port
Reuse `core/` unchanged; replace the PC shell with on-phone camera capture and a
cast/HDMI projection path. This is why the core is kept I/O-free from day one.

## Out of scope (for now)

- Permanent vertical mounting and glue-as-you-go (we chose flat + removable).
- Robotic/automatic placement — a human places every cap.
- Selling/cloud/multi-user features.

## Open items to confirm

- Projector and phone specs (see `docs/HARDWARE.md`).
- Whether to keep brand ID deferred or pull it into the POC.
- A first real target image once the designer (M1) is working.
