"""Find caps similar to a given cap — self-check + dataset navigation.

Score = ring-signature distance (visual layout, rotation-invariant) plus a
mosaic-colour CIEDE2000 term (scaled), so two caps must look alike both in
radial structure and in at-distance colour to rank close. Use it to verify
recognition (scan the same physical cap twice — its earlier record should be
the top hit) and to group duplicates in the inventory.

    PYTHONPATH=src python -m cap_mosaic.app.similar --db dataset/caps.db --cap 130
    PYTHONPATH=src python -m cap_mosaic.app.similar --db dataset/caps.db --latest
"""

from __future__ import annotations

import argparse

import numpy as np

from ..core.palette import ciede2000, rgb_to_lab
from ..data.store import CapDataset
from .cap_signature import MODEL_NAME, signature_distance

COLOR_WEIGHT = 0.02  # dE ~10 contributes ~0.2 — comparable to a real sig gap


def similar_caps(db: CapDataset, cap_id: int, k: int = 5) -> list[tuple[int, float]]:
    """Top-`k` (other_cap_id, score) most similar to `cap_id`; lower = closer."""
    embs = dict(db.get_embeddings(MODEL_NAME))
    if cap_id not in embs:
        raise ValueError(f"cap {cap_id} has no {MODEL_NAME} signature (run backfill)")
    caps = {c.id: c for c in db.caps()}
    ref_sig = np.asarray(embs[cap_id])
    ref = caps[cap_id]
    ref_lab = rgb_to_lab(ref.mosaic_rgb or ref.rgb)

    scored: list[tuple[int, float]] = []
    for cid, sig in embs.items():
        if cid == cap_id or cid not in caps:
            continue
        c = caps[cid]
        d_sig = signature_distance(ref_sig, np.asarray(sig))
        d_col = ciede2000(ref_lab, rgb_to_lab(c.mosaic_rgb or c.rgb))
        scored.append((cid, d_sig + COLOR_WEIGHT * d_col))
    scored.sort(key=lambda t: t[1])
    return scored[:k]


def _montage(db: CapDataset, cap_id: int, ranked, out_path: str) -> None:
    from PIL import Image, ImageDraw

    caps = {c.id: c for c in db.caps(with_frames=True)}
    ids = [cap_id] + [cid for cid, _ in ranked]
    cw, ch = 150, 175
    img = Image.new("RGB", (cw * len(ids), ch), (28, 28, 28))
    d = ImageDraw.Draw(img)
    for i, cid in enumerate(ids):
        c = caps.get(cid)
        x = i * cw
        if c and c.frames:
            try:
                im = Image.open(c.frames[0].path).convert("RGB").resize((128, 128))
                img.paste(im, (x + 11, 8))
            except OSError:
                pass
        label = f"query #{cid}" if i == 0 else f"#{cid}  d={ranked[i-1][1]:.2f}"
        d.text((x + 11, 145), label, fill=(255, 220, 120))
    img.save(out_path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-similar", description=__doc__)
    ap.add_argument("--db", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--cap", type=int, help="query cap id")
    g.add_argument("--latest", action="store_true", help="use the newest cap")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--montage", default=None, help="write a comparison PNG here")
    args = ap.parse_args(argv)

    with CapDataset(args.db) as db:
        cap_id = db.last_cap_id() if args.latest else args.cap
        ranked = similar_caps(db, cap_id, k=args.k)
        caps = {c.id: c for c in db.caps()}
        print(f"caps similar to #{cap_id} (field {caps[cap_id].rgb}):")
        for cid, score in ranked:
            c = caps[cid]
            print(f"  #{cid:>3}  score {score:.2f}  field {c.rgb}  mosaic {c.mosaic_rgb}")
        if args.montage:
            _montage(db, cap_id, ranked, args.montage)
            print(f"montage -> {args.montage}")


if __name__ == "__main__":
    main()
