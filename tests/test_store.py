import csv

from cap_mosaic.data.store import (
    SCHEMA_VERSION,
    CapDataset,
    FrameRecord,
    import_labels_csv,
)


def test_add_and_read_back_a_cap(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        cid = db.add_cap((120, 60, 40), captured_at="2026-06-24T00:00:00")
        assert db.count() == 1
        cap = db.caps()[0]
        assert cap.id == cid
        assert cap.rgb == (120, 60, 40)
        # Lab is derived and stored
        assert cap.lab[0] > 0
        assert db.colors() == [(120, 60, 40)]


def test_color_std_flags_a_glary_outlier_frame(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        # four consistent reads + one black (glare-clipped) outlier
        frames = [FrameRecord(i, f"f{i}.png", rgb=c) for i, c in enumerate(
            [(70, 72, 70), (71, 70, 69), (69, 71, 71), (70, 70, 70), (0, 0, 0)]
        )]
        db.add_cap((70, 71, 70), frames, captured_at="2026-06-24T00:00:00")
        cap = db.caps()[0]
        assert cap.n_frames == 5
        # the (0,0,0) frame should push the spread well above a clean read (~1-2)
        assert cap.color_std is not None and cap.color_std > 10


def test_frames_roundtrip_with_their_colors(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        frames = [FrameRecord(0, "a.png", rgb=(10, 20, 30), sha256="abc")]
        db.add_cap((10, 20, 30), frames, captured_at="t")
        cap = db.caps(with_frames=True)[0]
        assert len(cap.frames) == 1
        assert cap.frames[0].path == "a.png"
        assert cap.frames[0].rgb == (10, 20, 30)
        assert cap.frames[0].lab is not None  # derived for the frame too
        assert cap.frames[0].sha256 == "abc"


def test_embedding_store_and_schema_version(tmp_path):
    path = tmp_path / "caps.db"
    with CapDataset(path) as db:
        cid = db.add_cap((1, 2, 3), captured_at="t")
        db.add_embedding(cid, "clip-v1", [0.1, 0.2, 0.3], created_at="t")
        version = db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        row = db.conn.execute(
            "SELECT dim FROM embedding WHERE cap_id = ?", (cid,)
        ).fetchone()
        assert row["dim"] == 3


def test_marking_frac_roundtrips(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        db.add_cap((235, 235, 235), captured_at="t", marking_frac=0.34)
        cap = db.caps()[0]
        assert cap.marking_frac is not None
        assert abs(cap.marking_frac - 0.34) < 1e-6


def test_v1_db_upgrades_in_place_to_v2(tmp_path):
    import sqlite3

    # Build a v1 database by hand (schema v1 + user_version=1), with one cap row.
    from cap_mosaic.data.store import _SCHEMA_V1

    path = tmp_path / "caps.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA_V1)
    conn.execute("PRAGMA user_version = 1")
    conn.execute(
        "INSERT INTO cap (captured_at, r, g, b, lab_l, lab_a, lab_b, n_frames, source) "
        "VALUES ('t', 10, 20, 30, 5, 0, 0, 0, 'legacy')"
    )
    conn.commit()
    conn.close()

    # Opening with current code must add marking_frac and preserve the row.
    with CapDataset(path) as db:
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        cap = db.caps()[0]
        assert cap.rgb == (10, 20, 30)
        assert cap.marking_frac is None  # legacy row has no value, not a crash


def test_ambiguous_flag(tmp_path):
    with CapDataset(tmp_path / "caps.db") as db:
        # clean cap: low marking, stable across frames -> trustworthy
        db.add_cap((220, 220, 220), captured_at="t", marking_frac=0.30, color_std=1.0)
        # near-50/50 field/logo split -> ambiguous (which cluster is the field?)
        db.add_cap((174, 82, 68), captured_at="t", marking_frac=0.49, color_std=2.0)
        # unstable read: frames disagree (field cluster flipped) -> ambiguous
        db.add_cap((174, 180, 178), captured_at="t", marking_frac=0.31, color_std=34.0)
        clean, by_marking, by_std = db.caps()
        assert clean.is_ambiguous is False
        assert by_marking.is_ambiguous is True
        assert by_std.is_ambiguous is True


def test_delete_cap_removes_row_frames_and_crops(tmp_path):
    crop = tmp_path / "cap_0000_f0.png"
    crop.write_bytes(b"x")
    with CapDataset(tmp_path / "caps.db") as db:
        keep = db.add_cap((1, 2, 3), captured_at="t")
        drop = db.add_cap(
            (9, 9, 9), [FrameRecord(0, str(crop))], captured_at="t"
        )
        assert db.last_cap_id() == drop
        assert db.delete_cap(drop) is True
        assert db.count() == 1
        assert db.last_cap_id() == keep
        assert not crop.exists()  # crop file removed from disk
        # its frames are gone too (cascade)
        assert db.conn.execute(
            "SELECT COUNT(*) FROM frame WHERE cap_id = ?", (drop,)
        ).fetchone()[0] == 0
        assert db.delete_cap(9999) is False  # unknown id


def test_reopen_is_idempotent(tmp_path):
    path = tmp_path / "caps.db"
    with CapDataset(path) as db:
        db.add_cap((5, 5, 5), captured_at="t")
    # opening again must not wipe data or re-run migrations destructively
    with CapDataset(path) as db:
        assert db.count() == 1


def test_import_legacy_labels_csv_links_crops(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    for k in range(3):
        (crops / f"cap_0000_f{k}.png").write_bytes(b"x")
    csv_path = tmp_path / "labels.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "r", "g", "b", "n_frames"])
        w.writerow([0, 67, 122, 150, 5])

    with CapDataset(tmp_path / "caps.db") as db:
        n = import_labels_csv(db, csv_path, crops)
        assert n == 1
        cap = db.caps(with_frames=True)[0]
        assert cap.rgb == (67, 122, 150)
        assert len(cap.frames) == 3
