"""Interactive projector->table calibration (real-rig step, Milestone 2).

Projects four numbered crosshair markers, you measure where each one lands on the
table in millimetres (against a tape measure or a taped rectangle), type those
in, and it solves + saves the homography. Then it projects a known rectangle so
you can confirm true 1:1 scale with a ruler.

    python -m cap_mosaic.app.calibrate --out calibration/table.json --display-x 1920

Pick a table origin (e.g. a taped corner): +x to the right, +y away from you,
millimetres. Measure each crosshair's CENTRE from that origin. Use the SAME
--proj-width/--proj-height here and in the build so projector-pixel space agrees.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from ..procam.calibrate import Calibration
from ..procam.display import Projector

BLACK = (0, 0, 0)
MARK = (0, 255, 90)
TEXT = (180, 180, 180)


def marker_positions(w: int, h: int, margin: float) -> list[tuple[float, float]]:
    """Four markers inset by `margin` (fraction): TL, TR, BR, BL in proj px."""
    mx, my = margin * w, margin * h
    return [(mx, my), (w - mx, my), (w - mx, h - my), (mx, h - my)]


def draw_markers(
    w: int, h: int, markers: list[tuple[float, float]], arm: int = 40
) -> Image.Image:
    img = Image.new("RGB", (w, h), BLACK)
    d = ImageDraw.Draw(img)
    for i, (x, y) in enumerate(markers, start=1):
        d.line([(x - arm, y), (x + arm, y)], fill=MARK, width=3)
        d.line([(x, y - arm), (x, y + arm)], fill=MARK, width=3)
        d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=MARK, width=2)
        d.text((x + arm + 6, y - 8), str(i), fill=MARK)
    d.text((w // 2 - 120, 12), "measure each marker centre (mm), type in terminal", fill=TEXT)
    return img


def verification_pattern(
    cal: Calibration, rect_w_mm: float, rect_h_mm: float, bar_mm: float = 100.0
) -> Image.Image:
    """A table-space rectangle + a `bar_mm` scale bar, drawn in projector px."""
    img = Image.new("RGB", (cal.proj_width, cal.proj_height), BLACK)
    d = ImageDraw.Draw(img)
    corners = [(0, 0), (rect_w_mm, 0), (rect_w_mm, rect_h_mm), (0, rect_h_mm)]
    pts = [cal.table_mm_to_proj_px(x, y) for x, y in corners]
    d.line(pts + [pts[0]], fill=MARK, width=3)
    # a labelled scale bar near the origin
    b0 = cal.table_mm_to_proj_px(10, 10)
    b1 = cal.table_mm_to_proj_px(10 + bar_mm, 10)
    d.line([b0, b1], fill=(255, 255, 0), width=4)
    d.text(((b0[0] + b1[0]) / 2 - 30, b0[1] - 18), f"{bar_mm:.0f} mm", fill=(255, 255, 0))
    return img


def _ask_point(prompt: str) -> tuple[float, float]:
    while True:
        raw = input(prompt).replace(",", " ").split()
        try:
            x, y = float(raw[0]), float(raw[1])
            return (x, y)
        except (ValueError, IndexError):
            print("  please type two numbers, e.g.  120 80")


def run(
    out_path: str,
    proj_width: int,
    proj_height: int,
    display_x: int,
    margin: float,
) -> Calibration:
    markers_px = marker_positions(proj_width, proj_height, margin)
    proj = Projector(monitor_x=display_x)
    try:
        img = draw_markers(proj_width, proj_height, markers_px)
        proj.show(img, 1)
        print("\nFour markers are on the table. Measure each centre from your origin.")
        table_mm: list[tuple[float, float]] = []
        labels = ["1 (top-left)", "2 (top-right)", "3 (bottom-right)", "4 (bottom-left)"]
        for label, (px, py) in zip(labels, markers_px):
            proj.show(img, 1)  # keep the window refreshed
            pt = _ask_point(f"  marker {label} table mm 'x y': ")
            table_mm.append(pt)
        cal = Calibration.from_correspondences(
            table_mm, markers_px, proj_width, proj_height
        )
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        cal.save(out_path)
        print(f"\nsaved calibration -> {out_path}")

        # 1:1 verification over the measured span
        xs = [p[0] for p in table_mm]
        ys = [p[1] for p in table_mm]
        rect_w = max(xs) - min(xs)
        rect_h = max(ys) - min(ys)
        verify = verification_pattern(cal, rect_w, rect_h)
        proj.show(verify, 1)
        print(
            f"\nVerification: a {rect_w:.0f} x {rect_h:.0f} mm rectangle and a "
            "100 mm bar are projected.\nMeasure the yellow bar with a ruler -- it "
            "should read 100 mm. Press a key in the projector window to finish."
        )
        proj.wait_key(0)
        return cal
    finally:
        proj.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-calibrate", description=__doc__)
    ap.add_argument("--out", required=True, help="calibration JSON output path")
    ap.add_argument("--proj-width", type=int, default=1920, help="projector pixel width")
    ap.add_argument("--proj-height", type=int, default=1080, help="projector pixel height")
    ap.add_argument(
        "--display-x",
        type=int,
        default=0,
        help="virtual-desktop X of the projector monitor (e.g. primary width)",
    )
    ap.add_argument(
        "--margin", type=float, default=0.12, help="marker inset as a fraction of the frame"
    )
    args = ap.parse_args(argv)
    run(args.out, args.proj_width, args.proj_height, args.display_x, args.margin)


if __name__ == "__main__":
    main()
