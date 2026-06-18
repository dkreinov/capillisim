"""Card-driven build: read a cap from the card and decide accept/reject.

This module holds the device-independent decision logic (testable headless). The
live capture + projector loop is added in ``main`` (real-rig only).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.matcher import Match, Matcher
from ..core.plan import PlannedCell
from ..vision.card_reader import CapReading, CardCapReader


@dataclass
class FrameResult:
    reading: CapReading | None  # None = no card visible
    match: Match | None

    @property
    def state(self) -> str:
        if self.reading is None:
            return "idle"
        if self.match is not None and self.match.accepted:
            return "accept"
        return "reject"

    @property
    def cell(self) -> PlannedCell | None:
        return self.match.cell if self.match is not None else None


def process_frame(frame_rgb, reader: CardCapReader, matcher: Matcher) -> FrameResult:
    """Read a cap from the card in `frame_rgb` and match it to the plan."""
    reading = reader.read(frame_rgb)
    if reading is None:
        return FrameResult(None, None)
    return FrameResult(reading, matcher.match(reading.rgb))


# --------------------------------------------------------------------------- #
# Live rig loop (real-rig only — not unit-tested).                            #
# --------------------------------------------------------------------------- #


def _open_mjpeg(url: str, timeout: float = 10.0):
    import base64
    import urllib.request
    from urllib.parse import unquote, urlsplit, urlunsplit

    parts = urlsplit(url)
    headers, netloc = {}, parts.netloc
    if "@" in netloc:
        userinfo, netloc = netloc.rsplit("@", 1)
        user, _, pwd = userinfo.partition(":")
        token = base64.b64encode(f"{unquote(user)}:{unquote(pwd)}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return urllib.request.urlopen(urllib.request.Request(clean, headers=headers), timeout=timeout)


def _mjpeg_frames(url: str):
    stream = _open_mjpeg(url)
    buf = b""
    while True:
        chunk = stream.read(8192)
        if not chunk:
            return
        buf += chunk
        a = buf.find(b"\xff\xd8")
        b = buf.find(b"\xff\xd9", a + 2) if a != -1 else -1
        while a != -1 and b != -1:
            yield buf[a:b + 2]
            buf = buf[b + 2:]
            a = buf.find(b"\xff\xd8")
            b = buf.find(b"\xff\xd9", a + 2) if a != -1 else -1


def _beep():
    import winsound
    try:
        winsound.Beep(380, 150)
        winsound.Beep(240, 350)
    except Exception:
        pass


def _overlay_reject(img):
    from PIL import ImageDraw

    d = ImageDraw.Draw(img)
    w, h = img.size
    cx, cy, r = w // 2, h // 2, min(w, h) // 4
    d.line([cx - r, cy - r, cx + r, cy + r], fill=(235, 40, 40), width=max(6, w // 64))
    d.line([cx - r, cy + r, cx + r, cy - r], fill=(235, 40, 40), width=max(6, w // 64))
    return img


def main(argv: list[str] | None = None) -> None:
    import argparse
    import io
    import threading
    import time
    from collections import deque

    import numpy as np
    from PIL import Image

    from ..core.plan import GridPlan
    from ..procam.calibrate import Calibration
    from ..procam.display import Projector
    from ..procam.render import render_projection

    ap = argparse.ArgumentParser(prog="cap-mosaic-card-build", description=__doc__)
    ap.add_argument("--plan", required=True, help="plan .capproj.json")
    ap.add_argument("--url", required=True, help="phone MJPEG /video URL")
    ap.add_argument("--calibration", help="projector calibration JSON")
    ap.add_argument("--no-calibration", action="store_true", help="fit plan to projector frame")
    ap.add_argument("--proj-width", type=int, default=1920)
    ap.add_argument("--proj-height", type=int, default=1080)
    ap.add_argument("--display-x", type=int, default=1920, help="projector monitor X offset")
    ap.add_argument("--reject-threshold", type=float, default=None)
    ap.add_argument("--smooth", type=int, default=8, help="frames of temporal median smoothing")
    ap.add_argument("--refresh-ms", type=int, default=40)
    ap.add_argument("--save", help="plan state output path (default: the plan file)")
    args = ap.parse_args(argv)

    plan = GridPlan.load(args.plan)
    matcher = Matcher(plan, args.reject_threshold) if args.reject_threshold is not None else Matcher(plan)
    reader = CardCapReader()
    save_path = args.save or args.plan
    if args.no_calibration:
        cal = Calibration.fit_to_frame(plan.width_mm, plan.height_mm, args.proj_width, args.proj_height)
    elif args.calibration:
        cal = Calibration.load(args.calibration)
    else:
        raise SystemExit("provide --calibration <file> or --no-calibration")

    print(f"card build: plan '{plan.title}' {plan.filled_count}/{plan.count} filled. "
          "Place a cap on the card. SPACE=place accepted cap, Q=quit.")

    buf: deque = deque(maxlen=max(1, args.smooth))
    last_state, last_beep, placed = None, 0.0, 0
    end = time.time() + 3600
    while time.time() < end:
        try:
            proj = Projector(monitor_x=args.display_x)
            for jpg in _mjpeg_frames(args.url):
                try:
                    frame = np.asarray(Image.open(io.BytesIO(jpg)).convert("RGB"))
                except Exception:
                    continue
                reading = reader.read(frame)
                if reading is None:
                    state, cell = "idle", None
                    buf.clear()
                else:
                    buf.append(reading.rgb)
                    smoothed = tuple(int(v) for v in np.median(np.asarray(buf), axis=0))
                    m = matcher.match(smoothed)
                    state = "accept" if m.accepted else "reject"
                    cell = m.cell

                out = render_projection(plan, cal, highlight=(cell if state == "accept" else None))
                if state == "reject":
                    out = _overlay_reject(out)
                key = proj.show(out, max(1, args.refresh_ms))
                if key in (ord("q"), 27):
                    return
                if state == "reject" and last_state != "reject" and time.time() - last_beep > 1.2:
                    threading.Thread(target=_beep, daemon=True).start()
                    last_beep = time.time()
                if key == 32 and state == "accept" and cell is not None:
                    matcher.place(cell)
                    plan.save(save_path)
                    placed += 1
                    buf.clear()
                    print(f"  placed {cell.color_name} @ r{cell.row} c{cell.col}  ({plan.filled_count}/{plan.count})")
                last_state = state
        except Exception as e:
            print(f"rebuild: {e}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()
