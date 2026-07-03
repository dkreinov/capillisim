"""Backfill cap diameters from stored crops.

The crop window's physical width is known (``crop_span_mm``; legacy crops are
37.8 mm), so a cap's diameter can be recovered from its crop: mask what isn't
card-white, erase the thin printed circle line, measure the biggest blob.

One honest limit: on legacy 37.8 mm crops a measurement at >= 33 mm is
indistinguishable from the detector locking onto the printed card circle
(36 mm), so those are left NULL rather than stored wrong — a live re-scan
measures them properly off the full frame.

    PYTHONPATH=src python -m cap_mosaic.app.backfill_diameter --db dataset/caps.db
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from ..data.store import CapDataset

LEGACY_SPAN_MM = 37.8
# On a legacy-span crop, >= this reads as "the card circle, not the cap".
CIRCLE_LOCK_MM = 33.0


def crop_diameter_mm(crop_rgb: np.ndarray, span_mm: float) -> float | None:
    """Diameter of the cap blob in a crop whose full width spans `span_mm`."""
    import cv2

    a = np.asarray(crop_rgb, dtype=np.uint8)
    n = min(a.shape[:2])
    px_per_mm = n / span_mm
    mask = (~np.all(a >= 215, axis=2)).astype(np.uint8) * 255
    k = max(3, int(round(1.5 * px_per_mm)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    # area-equivalent diameter: a thin printed-line fragment attached to the
    # blob barely changes the area, whereas it inflates minEnclosingCircle to
    # the card circle. 2*sqrt(A/pi) is robust to those attachments.
    area = cv2.contourArea(max(cnts, key=cv2.contourArea))
    dia = 2.0 * float(np.sqrt(area / np.pi)) / px_per_mm
    return dia if dia >= 10.0 else None


def backfill_diameters(db: CapDataset, verbose: bool = False) -> int:
    """Measure + store diameters for caps that lack one; returns update count."""
    n = 0
    for cap in db.caps(with_frames=True):
        if cap.diameter_mm is not None:
            continue
        span = cap.crop_span_mm or LEGACY_SPAN_MM
        dias = []
        for fr in cap.frames:
            p = Path(fr.path)
            if not p.exists():
                continue
            try:
                crop = np.asarray(Image.open(p).convert("RGB"))
            except OSError:
                continue
            d = crop_diameter_mm(crop, span)
            if d is not None:
                dias.append(d)
        if not dias:
            continue
        dia = float(np.median(dias))
        if span <= LEGACY_SPAN_MM + 0.1 and dia >= CIRCLE_LOCK_MM:
            if verbose:
                print(f"  cap {cap.id}: {dia:.1f}mm ~ card circle lock -> NULL", flush=True)
            continue  # can't trust it on a tight crop; live re-scan measures truly
        db.set_diameter(cap.id, round(dia, 1))
        if verbose:
            print(f"  cap {cap.id}: Ø{dia:.1f}mm", flush=True)
        n += 1
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-backfill-diameter", description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    with CapDataset(args.db) as db:
        n = backfill_diameters(db, verbose=args.verbose)
        caps = db.caps()
        classes: dict[str, int] = {}
        for c in caps:
            classes[c.size_class or "unmeasured"] = classes.get(c.size_class or "unmeasured", 0) + 1
        import numpy as _np

        vals = [c.diameter_mm for c in caps if c.diameter_mm is not None]
        med = f"{_np.median(vals):.1f}" if vals else "n/a"
        print(f"measured {n} caps | median {med} mm | classes: {classes}")


if __name__ == "__main__":
    main()
