"""Project a finished plan onto the board to build it by hand.

Two projector modes (keys):
  S  stencil  — every cell lit in its cap colour (drop each cap on its disc)
  C  colour   — only the current colour's cells lit (glue one colour at a time)
  N / P       — next / previous colour (also switches to colour mode)
  Q           — quit

Like ``build_loop.run_loop``, the display and key input are injected callables,
so the loop runs and tests headless; ``main`` wires the real fullscreen projector
and OpenCV keys on the rig.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from PIL import Image

from ..core.plan import GridPlan
from ..procam.calibrate import Calibration
from ..procam.render import render_stencil

Display = Callable[[Image.Image], None]      # show a projector frame
KeySource = Callable[[], str | None]         # next key char, or None to quit

RGB = tuple[int, int, int]


class ProjectSession:
    """Live projection state: which mode, and which colour is active."""

    def __init__(self, plan: GridPlan, cal: Calibration):
        self.plan = plan
        self.cal = cal
        self.mode = "stencil"  # "stencil" | "colour"
        # distinct cap colours, most-used first (the order you'd glue them)
        counts = Counter(tuple(c.rgb) for c in plan.cells if not c.is_hole)
        self.colours: list[RGB] = [rgb for rgb, _ in counts.most_common()]
        self.ci = 0

    def current_colour(self) -> RGB | None:
        return self.colours[self.ci] if self.colours else None

    def frame(self) -> Image.Image:
        if self.mode == "colour" and self.colours:
            return render_stencil(self.plan, self.cal, color=self.current_colour())
        return render_stencil(self.plan, self.cal)


def run_projection(session: ProjectSession, display: Display, key_source: KeySource):
    """Drive the projector until `key_source` returns 'q' or None."""
    display(session.frame())  # initial full stencil
    while True:
        k = key_source()
        if k is None or k == "q":
            break
        if k == "s":
            session.mode = "stencil"
        elif k == "c":
            session.mode = "colour"
        elif k == "n" and session.colours:
            session.ci = (session.ci + 1) % len(session.colours)
            session.mode = "colour"
        elif k == "p" and session.colours:
            session.ci = (session.ci - 1) % len(session.colours)
            session.mode = "colour"
        else:
            continue  # unknown key: no redraw
        display(session.frame())
    return session


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - needs a projector
    import argparse

    from ..procam.display import Projector

    ap = argparse.ArgumentParser(prog="cap-mosaic-project", description=__doc__)
    ap.add_argument("--plan", required=True, help="a .capproj.json plan")
    ap.add_argument("--calibration", help="calibration/table.json; else fit-to-frame")
    ap.add_argument("--display-x", type=int, default=0, help="projector monitor x offset")
    ap.add_argument("--proj-width", type=int, default=1920)
    ap.add_argument("--proj-height", type=int, default=1080)
    args = ap.parse_args(argv)

    plan = GridPlan.load(args.plan)
    if args.calibration:
        cal = Calibration.load(args.calibration)
    else:
        cal = Calibration.fit_to_frame(plan.width_mm, plan.height_mm,
                                       args.proj_width, args.proj_height)
    session = ProjectSession(plan, cal)

    proj = Projector(monitor_x=args.display_x)
    key_map = {ord(c): c for c in "scnpq"}

    def key_source() -> str | None:
        return key_map.get(proj.wait_key(0), "")  # unknown keys -> no-op ""

    try:
        proj.show(session.frame(), 1)
        run_projection(session, lambda im: proj.show(im, 1), key_source)
    finally:
        proj.close()


if __name__ == "__main__":  # pragma: no cover
    main()
