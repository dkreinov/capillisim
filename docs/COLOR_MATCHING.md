# Color Matching & the Placement-Quality Threshold

Date: 2026-06-24. Purpose: record the design decision and the supporting research
for **how we decide whether a cap is "good enough" to place in a cell, or whether
the cell should stay empty.** This is the single most important tunable in the
build loop, and we cannot calibrate it until we have a true-size colour print on
the rig, so the reasoning is captured here for when we can.

## The decision, stated precisely

When planning a mosaic (and again live, cap-in-hand), each candidate cell has a
*target colour* and each cap has a *measured colour*. We compute their perceptual
distance and **place the cap only if that distance is within a threshold**;
otherwise we **leave the cell empty and seek a better cap**.

Locked principle (from the project owner):

> Better to have holes and seek new caps than to fill a cell with a bad colour.

A hole reads as deliberate negative space / shadow. A wrong-hue cap (e.g. a
**purple cap forced into a blue cell**) reads as a *mistake* and is more damaging
to the piece than the missing tile. So the threshold is a **quality gate**, not
merely a nearest-neighbour assignment.

This is already implemented as `reject_threshold` in
`core/matcher.py` (`accepted = delta_e <= reject_threshold`). What is *not* yet
decided is the **value** of that threshold and its **shape** (scalar vs.
component-weighted). This document is the basis for choosing both.

## Colour space & metric (settled)

- Compare colours **perceptually**, never in raw RGB. Convert to **CIELAB** and
  use **CIEDE2000 (ΔE₀₀)**, the modern standard with the best correlation to
  human vision. (Already the project convention; see `core/palette.py`.)

## What the research says about thresholds

There *is* a proven framework for this kind of accept/reject decision: the
**two-threshold model — Perceptibility Threshold (PT) vs. Acceptability Threshold
(AT)**. The canonical measurement (Paravina et al., dental colour-matching, large
observer panel — the most-cited study because it measured *both* thresholds
rigorously):

| Threshold | ΔE₀₀ | Meaning |
|-----------|------|---------|
| **PT** (perceptibility) | **≈ 1.2** | Below this, observers cannot see a difference. |
| **AT** (acceptability)  | **≈ 2.7** | Below this, observers see it but accept it; above, they call it a mismatch. |

General industry buckets agree: ΔE₀₀ ≤1 invisible; 1–2 only a trained eye;
**2–3.5 the commercial acceptability limit**; >3.5 clearly wrong.

Conceptually, our `reject_threshold` is an **AT**: "different but acceptable" →
place; "mismatch" → leave the hole.

## Why we cannot just use 2.7

Those studies use **side-by-side, full-field, close viewing** — the *hardest*
case for the eye. A cap mosaic is the opposite regime:

- **Discrete tiles + viewing distance.** Caps are large tiles viewed from metres
  away; the eye **spatially blends** them (optical mixing — see `PRIOR_ART.md`).
  Per-cap colour error that would fail at arm's length disappears at distance, so
  our *effective* AT is **higher (more tolerant) than 2.7** — possibly much
  higher. The exact figure depends on cap size and viewing distance and is **not
  published anywhere** for our case.

This means: **2.7 ΔE₀₀ is a conservative floor**, and the real working threshold
must be measured on the rig.

## How we will calibrate (deferred — needs the rig)

Blocked: we cannot run this yet because we cannot print the true-size colour
target. When the rig allows it:

1. **Start at the AT anchor**, ΔE₀₀ ≈ 2.7, as a safe floor.
2. **Ramp test.** Lay out caps at increasing ΔE₀₀ from a fixed target colour
   (e.g. steps of 2, 4, 6, 8, 10). Stand at the painting's real viewing distance.
   Find the step where the mismatch becomes objectionable. That ΔE is *our*
   threshold for *our* tile size and distance.
3. The threshold **scales with viewing distance and tile size** — bigger caps or
   closer viewing → tighter threshold. See `SIZING_AND_VIEWING.md`.

## The refinement that handles the purple-in-blue case

A single scalar ΔE is blunt. Pointillism / optical mixing **forgives lightness
and chroma error** (the eye reconstructs tone from neighbouring tiles) but
**punishes hue error** (purple among blue screams "mistake"). ΔE₀₀ already
down-weights lightness somewhat, but we can encode this explicitly by **splitting
the gate** into the CIEDE2000 components:

- **loose** tolerance on **ΔL'** (lightness) and **ΔC'** (chroma),
- **tight** tolerance on **ΔH'** (hue).

i.e. accept only if `ΔH' ≤ hue_tol AND ΔL' ≤ light_tol AND ΔC' ≤ chroma_tol`
(or a weighted combination), instead of a single `ΔE₀₀ ≤ threshold`. This
directly encodes "a slightly-too-dark blue is fine, a purple is not," which a
scalar cannot express. Recommended as the eventual shape of `reject_threshold`.

## Status / open items

- [x] Metric chosen: CIEDE2000 in CIELAB.
- [x] Gate implemented as `reject_threshold` (scalar) in `core/matcher.py`.
- [x] Anchor value identified: AT ≈ 2.7 ΔE₀₀ (conservative floor).
- [ ] **Blocked on rig:** ramp-test calibration of the true threshold at real
      viewing distance + cap size.
- [ ] **Enhancement:** component-weighted (ΔH'/ΔL'/ΔC') gate to better reject
      hue errors while tolerating lightness/chroma error.
- [ ] Dataset feeds this: capture stores **true measured RGB only** (no palette
      bucketing); bucketing/clustering is decided per-painting at plan time from
      the real inventory. See `app/cap_capture.py`.

## Pipeline upgrades from pointillism research

We read the Stanford EE368 pointillism paper (Hong & Liu, *Create Pointillism Art
from Digital Images*) in full. Most of its techniques **do not transfer** — it
paints with *translucent, overlapping* dots, *many dots per pixel*, variable dot
*density* for tone (stippling), and rotated brushstrokes. We place **one opaque
cap per fixed grid cell**, so none of opacity / overlap / density / orientation
is available to us. But three ideas transfer directly, and each exposes a gap in
the current planner (`app/planner_designer.py`, `plan_from_image`), which today
does a naive independent per-cell `nearest(mean, fixed_10_palette)` — no
image-derived palette, no inventory awareness, no spatial blending, and **no
plan-time reject gate**.

1. **Palette from the image (k-means), not a fixed list.** Seurat used ≤11
   colours; the paper picks its primaries by **k-means on the input image**. Our
   planner still quantizes to the hard-coded 10-colour `DEFAULT_PALETTE`. Upgrade:
   derive the working palette per-painting by clustering the image *and*
   intersecting with the **actual cap inventory** (the dataset). This is the
   owner's stated intent (cluster real caps, decide needed colours per painting)
   and matches the research. Cluster in **CIELAB**, not RGB — the paper clusters
   in RGB and then has to hand-boost because RGB k-means skews dark; LAB avoids
   that.

2. **Optical mixing → spatial dithering (the big one).** Seurat represents an
   area that is "approximately one colour" with a *mix* of differently-coloured
   dots that blend in the eye at distance (e.g. red + blue dots for a shaded
   region). Translated to our medium: a target colour we have **no matching cap**
   for can still be produced by placing **neighbouring caps of colours we do
   have** so their average reads correct at viewing distance. Mechanism:
   **error-diffusion dithering** (Floyd–Steinberg) over the grid against the
   inventory palette, instead of independent per-cell nearest-match. Payoff: this
   is the principled way to **minimise holes** — it lets the inventory cover
   colours it doesn't literally contain, *without* the bad single-cell matches
   the reject gate would (correctly) reject. Dithering and the reject gate are
   complementary: dithering spreads quantization error spatially so the *local
   average* is right; the reject gate still vetoes any *individual* placement
   whose error is too large to be masked by blending.

3. **Hue is the dominant failure mode (confirms §"the purple-in-blue case").**
   The paper works in HSV specifically to manipulate hue/sat/value separately,
   and notes juxtaposition shifts perceived hue. This reinforces the
   component-weighted (tight ΔH', loose ΔL'/ΔC') reject gate: lightness/chroma
   error is masked by optical mixing, hue error is not.

**Sequencing.** (1) and the **plan-time reject gate** align with already-locked
decisions and are pure-core, headless-testable, *not* blocked on the rig — safe
to implement now. (2) dithering is a larger aesthetic change (it trades flat
colour fields for visible blended texture) — implement behind a flag and compare
with `simulate_distance` before adopting. (3) is the eventual shape of the gate.

## Sources

- Hong & Liu, *Create Pointillism Art from Digital Images* (Stanford EE368) —
  https://web.stanford.edu/class/ee368/Project_Autumn_1516/Reports/Hong_Liu.pdf
- Paravina et al., *Perceptibility and acceptability thresholds for colour
  differences in dentistry* — https://www.sciencedirect.com/science/article/abs/pii/S0300571213003175
- *Color difference* (ΔE, CIEDE2000, JND) — https://en.wikipedia.org/wiki/Color_difference
- Delta E and colour tolerance, CIE standards — https://skychemi.com/color-difference-formula-delta-e/
