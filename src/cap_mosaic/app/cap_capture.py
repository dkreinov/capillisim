"""Capture a cap dataset using the Cap Reading Card.

Place a cap on the card's circle; press SPACE to save several normalized,
colour-corrected crops of it (+ a labels row); Q to quit. The card auto-locates,
white-balances, and crops, so every image is consistently framed and lit — ideal
for a palette / inventory / embedding dataset.

    python -m cap_mosaic.app.cap_capture --out dataset --camera 0

Writes ``<out>/crops/cap_<NNNN>_f<k>.png`` (the colour-corrected crops) and a row
per cap in ``<out>/caps.db`` (SQLite; see ``data/store.py`` and
``docs/DATA_MODEL.md``): the true measured RGB/Lab as the **median across all
saved frames** (robust to a single glary frame), a per-frame colour spread as a
quality signal, and a link to each crop. No palette bucketing at capture time.
Re-running resumes the index.
"""

from __future__ import annotations

import argparse
import hashlib
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from ..data.store import CapDataset, FrameRecord
from ..vision.card_reader import (
    cap_present,
    crop_cap,
    detect_card,
    read_cap_field,
    white_balance,
)


def _median(values: list[float]) -> float:
    s = sorted(values)
    return s[len(s) // 2]


def _median_rgb(colors: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """Per-channel median of several colour readings (robust to one bad frame)."""
    n = len(colors)
    mid = n // 2

    def chan(i: int) -> int:
        vals = sorted(c[i] for c in colors)
        return int(vals[mid] if n % 2 else round((vals[mid - 1] + vals[mid]) / 2))

    return (chan(0), chan(1), chan(2))


def _ding():
    """A rising two-tone confirmation that a cap was saved."""
    import winsound
    try:
        winsound.Beep(880, 110)
        winsound.Beep(1320, 150)
    except Exception:
        pass


def _next_index(crops_dir: Path) -> int:
    existing = list(crops_dir.glob("cap_*_f0.png"))
    if not existing:
        return 0
    return 1 + max(int(p.name.split("_")[1]) for p in existing)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-capture", description=__doc__)
    ap.add_argument("--out", required=True, help="dataset output folder")
    ap.add_argument("--camera", type=int, default=0, help="USB camera index")
    ap.add_argument("--frames-per-cap", type=int, default=5)
    ap.add_argument("--size", type=int, default=128)
    ap.add_argument("--cam-width", type=int, default=1280)
    ap.add_argument("--cam-height", type=int, default=720)
    ap.add_argument("--auto", action="store_true", help="auto-save when a new cap settles (empty white circle between caps)")
    ap.add_argument("--auto-stable", type=int, default=6, help="frames a new colour must hold before auto-saving")
    args = ap.parse_args(argv)

    out = Path(args.out)
    crops = out / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    db = CapDataset(out / "caps.db")
    idx = _next_index(crops)

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise SystemExit(f"could not open camera index {args.camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.cam_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.cam_height)
    print(f"cap capture -> {out}  (start index {idx}). SPACE=save, Z=undo last, Q=quit.", flush=True)

    flash_until = 0.0
    flash_msg = ""
    captured = False  # has the current cap already been auto-saved?
    stable_col = None
    stable_n = 0
    FONT = cv2.FONT_HERSHEY_SIMPLEX

    def save_cap(h_use, col_use):
        nonlocal idx, flash_until, flash_msg
        frames: list[FrameRecord] = []
        fields: list[tuple[int, int, int]] = []
        marks: list[float] = []
        for fk in range(args.frames_per_cap):
            ok2, b2 = cap.read()
            if not ok2:
                continue
            r2 = cv2.cvtColor(b2, cv2.COLOR_BGR2RGB)
            h2 = detect_card(r2)
            if h2 is None:
                h2 = h_use
            wb = white_balance(r2, h2)
            crop = crop_cap(wb, h2, args.size)
            if crop is None:
                continue
            path = crops / f"cap_{idx:04d}_f{fk}.png"
            png = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(path), png)
            # the cap's true colour for this frame: dominant field, logo excluded
            fld = read_cap_field(wb, h2)
            col_f = fld[0] if fld else None
            if fld is not None:
                fields.append(fld[0])
                marks.append(fld[1])
            ok_buf, buf = cv2.imencode(".png", png)
            sha = hashlib.sha256(buf.tobytes()).hexdigest() if ok_buf else None
            frames.append(FrameRecord(frame_index=fk, path=str(path), rgb=col_f, sha256=sha))
            time.sleep(0.04)

        # robust per-cap values = median across frame reads (1 bad frame can't skew it)
        color = _median_rgb(fields) if fields else tuple(col_use)
        marking = _median(marks) if marks else None
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.add_cap(color, frames, captured_at=now, source="card_capture",
                   marking_frac=marking)
        threading.Thread(target=_ding, daemon=True).start()
        flash_msg, flash_until = f"SAVED #{idx}", time.time() + 0.8
        busy = f"  busy {int(marking * 100)}%" if marking else ""
        print(f"  saved cap #{idx}: {len(frames)} crops  rgb{color}{busy}", flush=True)
        idx += 1

    try:
        while True:
            ok, bgr = cap.read()
            if not ok:
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            h = detect_card(rgb)
            preview = cv2.resize(bgr, (640, 360))
            col = None
            if h is None:
                cv2.putText(preview, "no card in view", (12, 28), FONT, 0.7, (60, 60, 235), 2)
            else:
                wb = white_balance(rgb, h)
                present = cap_present(wb, h)
                fld = read_cap_field(wb, h) if present else None
                col = fld[0] if fld else None
                if col is not None:
                    cv2.rectangle(preview, (500, 232), (632, 348), (col[2], col[1], col[0]), -1)
                    cv2.rectangle(preview, (500, 232), (632, 348), (255, 255, 255), 2)
                    cv2.putText(preview, "field", (502, 226), FONT, 0.5, (255, 255, 255), 1)
                busy = int(fld[1] * 100) if fld else 0
                label = "empty (no cap)" if not present else f"cap #{idx}  rgb{col}  busy {busy}%"
                mode = "AUTO" if args.auto else "SPACE=save"
                cv2.putText(preview, f"{label}   [{mode}]", (12, 28), FONT, 0.6,
                            (170, 170, 170) if not present else (60, 235, 90), 2)
                if args.auto:
                    if not present:
                        captured, stable_n, stable_col = False, 0, None
                    elif col is not None:
                        if stable_col is not None and max(abs(a - b) for a, b in zip(col, stable_col)) < 14:
                            stable_n += 1
                        else:
                            stable_col, stable_n = col, 1
                        if stable_n == args.auto_stable and not captured:
                            save_cap(h, col)
                            captured = True
            if time.time() < flash_until:  # green SAVED confirmation
                cv2.rectangle(preview, (3, 3), (637, 357), (60, 235, 90), 6)
                cv2.putText(preview, flash_msg, (170, 195), FONT, 1.1, (60, 235, 90), 3)
            cv2.imshow("cap capture", preview)
            k = cv2.waitKey(30) & 0xFF
            if k in (ord("q"), 27):
                break
            if k == 32 and h is not None and col is not None:
                save_cap(h, col)
            if k == ord("z"):  # undo: remove the most recently saved cap
                last = db.last_cap_id()
                if last is not None and db.delete_cap(last):
                    idx = _next_index(crops)
                    captured = False
                    flash_msg, flash_until = f"REMOVED #{last}", time.time() + 0.8
                    print(f"  removed cap #{last}", flush=True)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        db.close()


if __name__ == "__main__":
    main()
