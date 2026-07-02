"""Backfill the mosaic (at-distance) colour for caps already in the dataset.

Caps captured before schema v3 have no ``mosaic_rgb``. This recomputes it from
their stored crops — linear-light mean per crop (``cap_color``), per-channel
median across the cap's frames — and writes it with ``set_mosaic``. Idempotent:
re-running recomputes the same values, so it's safe after new captures too.

    PYTHONPATH=src python -m cap_mosaic.app.backfill_mosaic --db dataset/caps.db

Prints a per-cap line and a quality report (frame-spread / ambiguity flags) so
suspect captures are visible.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from ..data.store import CapDataset
from .cap_color import median_rgb, mosaic_rgb_from_crop


def backfill(db: CapDataset, dry_run: bool = False, verbose: bool = False) -> int:
    """Compute + store mosaic_rgb for every cap that has readable crops.

    Returns the number of caps updated (or that would be, with ``dry_run``).
    """
    updated = 0
    for cap in db.caps(with_frames=True):
        mosaics = []
        for fr in cap.frames:
            p = Path(fr.path)
            if not p.exists():
                continue
            try:
                crop = np.asarray(Image.open(p).convert("RGB"))
            except OSError:
                continue
            mosaics.append(mosaic_rgb_from_crop(crop))
        if not mosaics:
            continue
        mosaic = median_rgb(mosaics)
        flag = " AMBIGUOUS" if cap.is_ambiguous else ""
        if verbose:
            print(f"  cap {cap.id:>3}  field {cap.rgb}  ->  mosaic {mosaic}"
                  f"  ({len(mosaics)} crops){flag}", flush=True)
        if not dry_run:
            db.set_mosaic(cap.id, mosaic)
        updated += 1
    return updated


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-backfill", description=__doc__)
    ap.add_argument("--db", required=True, help="path to caps.db")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)

    with CapDataset(args.db) as db:
        n = backfill(db, dry_run=args.dry_run, verbose=True)
        total = db.count()
        missing = sum(1 for c in db.caps() if c.mosaic_rgb is None)
        amb = sum(1 for c in db.caps() if c.is_ambiguous)
        print(f"\n{'would update' if args.dry_run else 'updated'} {n}/{total} caps"
              f" | without mosaic: {missing} | flagged ambiguous: {amb}")


if __name__ == "__main__":
    main()
