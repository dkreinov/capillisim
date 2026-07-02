import numpy as np
from PIL import Image

from cap_mosaic.app.backfill_mosaic import backfill
from cap_mosaic.data.store import CapDataset, FrameRecord


def _crop_png(path, color, n=64):
    """A crop-like PNG: solid colour disc on white."""
    img = np.full((n, n, 3), 250, np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    img[np.hypot(xx - n / 2, yy - n / 2) <= n / 2 - 2] = color
    Image.fromarray(img, "RGB").save(path)


def _db_with_caps(tmp_path):
    db = CapDataset(tmp_path / "caps.db")
    # cap A: 3 clean blue crops
    fa = []
    for k in range(3):
        p = tmp_path / f"a_f{k}.png"
        _crop_png(p, (40, 80, 160))
        fa.append(FrameRecord(k, str(p), rgb=(40, 80, 160)))
    a = db.add_cap((40, 80, 160), fa, captured_at="t")
    # cap B: no frames -> skipped
    b = db.add_cap((10, 10, 10), captured_at="t")
    return db, a, b


def test_backfill_sets_mosaic_from_crops_and_skips_frameless(tmp_path):
    db, a, b = _db_with_caps(tmp_path)
    n = backfill(db)
    caps = {c.id: c for c in db.caps()}
    assert n == 1
    assert caps[a].mosaic_rgb is not None
    # solid blue crop -> mosaic ~= the colour itself
    assert all(abs(x - y) <= 3 for x, y in zip(caps[a].mosaic_rgb, (40, 80, 160)))
    assert caps[b].mosaic_rgb is None  # nothing to compute from
    db.close()


def test_backfill_is_idempotent(tmp_path):
    db, a, _ = _db_with_caps(tmp_path)
    backfill(db)
    first = {c.id: c.mosaic_rgb for c in db.caps()}
    backfill(db)  # second run: same values, no error
    second = {c.id: c.mosaic_rgb for c in db.caps()}
    assert first == second
    db.close()


def test_dry_run_writes_nothing(tmp_path):
    db, a, _ = _db_with_caps(tmp_path)
    backfill(db, dry_run=True)
    assert all(c.mosaic_rgb is None for c in db.caps())
    db.close()
