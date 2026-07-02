# Handoff — current state

Resume anchor: what's built, what's pending. See `docs/ROADMAP.md` for the full
milestone plan and `docs/RESEARCH.md` for the dataset/technique shortlist.

## Built and tested (headless)

**Designer / core** (`core/`, `app/planner_designer.py`)
- Image → `GridPlan` with CIELAB k-means palette, curated presets
  (portrait/sunset/space), reject-gate holes, bare-white background holes.
- Thin-outline detect + thicken (`core/features.py`) so ~1-cap strokes survive.
- **Dither** (`core/dither.py`): CIELAB Floyd–Steinberg error diffusion over the
  cap grid — a small palette reads far better on gradients/tones.

**Estimator web app** (`app/webapp/`, see `docs/ESTIMATOR.md`)
- size ↔ distance solve, legibility floor, minimal size, effective colours.
- Distance sim = shrink-in-fixed-FOV, stay sharp, linear-light cap blending.
- Cap rendering: uniform auto-cropped real caps (`app/cap_crop.py`) + procedural,
  glued on a controllable **board colour**; region crop; colour isolate.
- **Hold-to-compare** original vs caps (`/target`); **printable cap map** PDF
  (`app/cap_map.py`, `/capmap`); **inventory gap** report from `caps.db`
  (have/need/short, report-only).

**Projector build** (`procam/render.py`, `app/project_plan.py`)
- **Stencil** (`render_stencil`): every cell lit in its cap colour at 1:1, plus a
  **per-colour pass** (light one colour at a time — glue it, then next).
- `project_plan` entrypoint with S/C/N/P/Q keys; display + keys injected as
  callables (headless-tested). `main` drives the real fullscreen projector.
- Interactive per-cap loop (`build_loop.run_loop`) from M3 still in place.

**Cap scanning** (`app/cap_capture.py`, `app/make_card.py`) — card-based capture
into `caps.db` with median-colour + busy-ness.

## Pending (needs the rig + this machine)

- On-rig projector calibration (`from_correspondences`) and a live
  stencil/per-colour verification — the projection code is done, untested on glass.
- Live phone stream for the interactive loop (snapshot path works today).
- Threshold tuning on real caps (reject ΔE, dither kernel, inventory tolerance).

## Next actions (from `docs/RESEARCH.md`)

- Import a cap dataset (images.cv / Roboflow / Kaggle) through `app/cap_crop.py`
  to grow `caps.db` so `real_only` and the inventory report have real coverage.
  Kaggle needs `KAGGLE_USERNAME` in `.env` (key already present).
- Consider an Atkinson dither kernel option for very small palettes.
- Later: hard inventory-constrained plans (decrement stock as cells fill).
