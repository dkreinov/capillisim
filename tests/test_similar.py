import numpy as np
from PIL import Image

from cap_mosaic.app.backfill_signatures import backfill_signatures
from cap_mosaic.app.similar import similar_caps
from cap_mosaic.data.store import CapDataset, FrameRecord


def _crop_png(path, body, ring=None, n=96):
    img = np.full((n, n, 3), 250, np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(xx - n / 2, yy - n / 2)
    img[r <= n * 0.42] = body
    if ring:
        img[(r > n * 0.20) & (r <= n * 0.28)] = ring
    Image.fromarray(img, "RGB").save(path)


def _add(db, tmp_path, tag, body, ring=None, rot=0):
    p = tmp_path / f"{tag}_f0.png"
    _crop_png(p, body, ring)
    if rot:
        Image.open(p).rotate(rot).save(p)
    return db.add_cap(body, [FrameRecord(0, str(p))], captured_at="t", mosaic_rgb=body)


def test_similar_ranks_the_near_duplicate_first(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        a = _add(db, tmp_path, "a", (30, 60, 160), ring=(230, 220, 90))
        dup = _add(db, tmp_path, "dup", (32, 62, 158), ring=(228, 222, 92), rot=90)
        other = _add(db, tmp_path, "other", (30, 60, 160))  # same colour, no ring
        backfill_signatures(db)
        ranked = similar_caps(db, a, k=2)
        assert ranked[0][0] == dup      # the rotated near-duplicate wins
        assert ranked[0][1] < ranked[1][1]  # and scores closer than the plain cap
