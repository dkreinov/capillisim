import numpy as np
from PIL import Image

from cap_mosaic.app.backfill_signatures import backfill_signatures
from cap_mosaic.app.cap_signature import MODEL_NAME, SIG_LEN
from cap_mosaic.data.store import CapDataset, FrameRecord


def _crop_png(path, color, n=64):
    img = np.full((n, n, 3), 250, np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    img[np.hypot(xx - n / 2, yy - n / 2) <= n / 2 - 2] = color
    Image.fromarray(img, "RGB").save(path)


def test_backfill_stores_a_signature_per_cap_and_is_idempotent(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        frames = []
        for k in range(3):
            p = tmp_path / f"a_f{k}.png"
            _crop_png(p, (40, 80, 160))
            frames.append(FrameRecord(k, str(p)))
        a = db.add_cap((40, 80, 160), frames, captured_at="t")
        db.add_cap((9, 9, 9), captured_at="t")  # frameless -> skipped

        n = backfill_signatures(db)
        assert n == 1
        embs = dict(db.get_embeddings(MODEL_NAME))
        assert set(embs) == {a}
        assert len(embs[a]) == SIG_LEN

        n2 = backfill_signatures(db)  # re-run replaces, doesn't duplicate
        assert n2 == 1
        assert len(db.get_embeddings(MODEL_NAME)) == 1
