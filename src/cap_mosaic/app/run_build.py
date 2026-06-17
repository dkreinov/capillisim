"""Live interactive build loop on the real rig (Milestone 3 entrypoint).

Loads a plan + a saved calibration, reads caps from the phone, projects the
target cell, and advances on a keypress. Capture defaults to polling the phone's
snapshot endpoint (reuses the Basic-auth path, no OpenCV needed to grab); pass
--stream for the lower-latency MJPEG path instead.

    python -m cap_mosaic.app.run_build \
        --plan plans/face.capproj.json \
        --calibration calibration/table.json \
        --url http://user:pass@192.168.1.42:8080/shot.jpg \
        --display-x 1920

Keys (focus the projector window): SPACE = placed -> next, S = skip this cap,
Q / Esc = quit. State is saved to the plan file after every placement.
"""

from __future__ import annotations

import argparse

from PIL import Image

from ..core.plan import GridPlan
from ..procam.calibrate import Calibration
from ..procam.display import Projector
from ..vision.cap_reader import (
    grab_snapshot,
    phone_frame_grabber,
    read_dominant_color,
)
from .build_loop import BuildSession


def _snapshot_source(url: str, timeout: float):
    def grab() -> Image.Image | None:
        try:
            return grab_snapshot(url, timeout=timeout)
        except Exception:  # transient drop -> skip this frame
            return None

    return grab


def _draw_preview(cv2, np, frame: Image.Image, rgb, match, center: float) -> None:
    bgr = cv2.cvtColor(np.asarray(frame.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    scale = 480.0 / w
    bgr = cv2.resize(bgr, (480, int(h * scale)))
    ph, pw = bgr.shape[:2]
    cw, ch = int(pw * center), int(ph * center)
    cv2.rectangle(
        bgr, ((pw - cw) // 2, (ph - ch) // 2), ((pw + cw) // 2, (ph + ch) // 2),
        (0, 255, 90), 1,
    )
    verdict = "ACCEPT" if match.accepted else "reject"
    target = match.cell.color_name if match.cell is not None else "-"
    txt = f"rgb{tuple(rgb)} -> {target} dE={match.delta_e:.1f} {verdict}"
    cv2.putText(bgr, txt, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.imshow("cap camera", bgr)


def run(args) -> None:
    plan = GridPlan.load(args.plan)
    cal = Calibration.load(args.calibration)
    session = BuildSession(plan, cal, args.reject_threshold)
    save_path = args.save or args.plan

    if args.stream:
        grab = phone_frame_grabber(args.url)
    else:
        grab = _snapshot_source(args.url, args.timeout)

    proj = Projector(monitor_x=args.display_x)
    cv2 = proj.cv2
    import numpy as np  # noqa: PLC0415

    placed = skipped = 0
    print(
        f"Build '{plan.title}': {plan.filled_count}/{plan.count} filled. "
        "SPACE=place, S=skip, Q=quit."
    )
    proj.show(session.projection(), 1)
    try:
        while True:
            frame = grab()
            if frame is None:
                if proj.wait_key(50) in (ord("q"), 27):
                    break
                continue
            rgb = read_dominant_color(frame, center_fraction=args.center)
            match = session.matcher.match(rgb)
            highlight = match.cell if match.accepted else None
            proj.show(session.projection(highlight=highlight), 1)
            if args.show_camera:
                _draw_preview(cv2, np, frame, rgb, match, args.center)
            key = proj.wait_key(args.refresh_ms)

            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                skipped += 1
                continue
            if key == 32:  # SPACE
                if match.accepted and match.cell is not None:
                    session.accept(match)
                    placed += 1
                    plan.save(save_path)
                    c = match.cell
                    print(
                        f"  placed {c.color_name} @ r{c.row} c{c.col}  "
                        f"({plan.filled_count}/{plan.count})  dE={match.delta_e:.1f}"
                    )
                else:
                    print("  cap rejected -- nothing to place; set it aside")
            if plan.filled_count >= plan.count:
                print("piece complete!")
                break
    finally:
        proj.close()
    print(f"done: placed {placed}, skipped {skipped}, filled {plan.filled_count}/{plan.count}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-build", description=__doc__)
    ap.add_argument("--plan", required=True, help="plan .capproj.json")
    ap.add_argument("--calibration", required=True, help="calibration JSON")
    ap.add_argument("--url", required=True, help="phone snapshot (or --stream MJPEG) URL")
    ap.add_argument("--stream", action="store_true", help="treat --url as an MJPEG stream")
    ap.add_argument("--display-x", type=int, default=0, help="projector monitor X offset")
    ap.add_argument("--center", type=float, default=0.5, help="central frame fraction to read")
    ap.add_argument("--reject-threshold", type=float, default=None, help="override dE reject")
    ap.add_argument("--timeout", type=float, default=5.0, help="snapshot request timeout (s)")
    ap.add_argument("--refresh-ms", type=int, default=60, help="loop key/refresh interval")
    ap.add_argument("--save", help="state output path (defaults to the plan file)")
    ap.add_argument("--show-camera", action="store_true", help="show a camera preview window")
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
