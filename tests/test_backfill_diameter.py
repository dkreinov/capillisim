import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image

from cap_mosaic.app.backfill_diameter import backfill_diameters, crop_diameter_mm
from cap_mosaic.data.store import CapDataset, FrameRecord

SPAN = 37.8


def _crop(path, cap_mm, span_mm=SPAN, n=128, ring=True):
    """Card-style crop: white bg + printed circle line + cap disc, known span."""
    px_per_mm = n / span_mm
    img = np.full((n, n, 3), 250, np.uint8)
    c = n // 2
    if ring:
        cv2.circle(img, (c, c), int(18.0 * px_per_mm), (150, 150, 150), 1)
    if cap_mm:
        cv2.circle(img, (c, c), int(cap_mm / 2 * px_per_mm), (30, 40, 120), -1)
    Image.fromarray(img, "RGB").save(path)


def test_crop_diameter_measures_a_crown():
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "c.png")
        _crop(p, 26.0)
        a = np.asarray(Image.open(p).convert("RGB"))
        d = crop_diameter_mm(a, SPAN)
        assert d is not None and abs(d - 26.0) < 2.0, d


def test_backfill_sets_diameter_and_skips_unmeasurable(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        pa = tmp_path / "a_f0.png"; _crop(pa, 26.0)
        a = db.add_cap((30, 40, 120), [FrameRecord(0, str(pa))], captured_at="t")
        pb = tmp_path / "b_f0.png"; _crop(pb, None)  # empty circle -> unmeasurable
        b = db.add_cap((9, 9, 9), [FrameRecord(0, str(pb))], captured_at="t")
        n = backfill_diameters(db)
        caps = {c.id: c for c in db.caps()}
        assert n == 1
        assert caps[a].diameter_mm is not None and abs(caps[a].diameter_mm - 26.0) < 2.0
        assert caps[a].size_class == "standard-26"
        assert caps[b].diameter_mm is None


def test_backfill_leaves_card_circle_locks_null(tmp_path):
    # a measurement that lands at ~the card circle (>=33mm on the 37.8 span)
    # is a detection artefact for a crown-sized cap batch -> keep NULL
    with CapDataset(tmp_path / "caps.db") as db:
        p = tmp_path / "c_f0.png"; _crop(p, 35.0)  # blob indistinguishable from circle lock
        c = db.add_cap((30, 40, 120), [FrameRecord(0, str(p))], captured_at="t")
        backfill_diameters(db)
        assert db.caps()[0].diameter_mm is None
