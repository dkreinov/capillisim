"""Backfill ring signatures (``ringsig-v1``) for every cap with readable crops.

The signature is the per-element median across the cap's frames — robust to a
single odd frame. INSERT OR REPLACE semantics make re-runs safe.

    PYTHONPATH=src python -m cap_mosaic.app.backfill_signatures --db dataset/caps.db
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from ..data.store import CapDataset
from .cap_signature import MODEL_NAME, cap_signature


def backfill_signatures(db: CapDataset) -> int:
    """Compute + store a signature for every cap with crops; returns count."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for cap in db.caps(with_frames=True):
        sigs = []
        for fr in cap.frames:
            p = Path(fr.path)
            if not p.exists():
                continue
            try:
                crop = np.asarray(Image.open(p).convert("RGB"))
            except OSError:
                continue
            sigs.append(cap_signature(crop))
        if not sigs:
            continue
        sig = np.median(np.stack(sigs), axis=0).astype(np.float32)
        db.add_embedding(cap.id, MODEL_NAME, sig.tolist(), created_at=now)
        n += 1
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-backfill-sig", description=__doc__)
    ap.add_argument("--db", required=True)
    args = ap.parse_args(argv)
    with CapDataset(args.db) as db:
        n = backfill_signatures(db)
        print(f"signatures stored for {n}/{db.count()} caps ({MODEL_NAME})")


if __name__ == "__main__":
    main()
