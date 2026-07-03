"""The scanner's recent-caps strip: last N scans, with deletions visible."""

import numpy as np
import cv2
import pytest

from cap_mosaic.app.cap_capture import (
    RECENT_N,
    _STRIP_H,
    _TILE,
    _thumb,
    recent_entries_from_db,
    render_recent_strip,
)
from cap_mosaic.data.store import CapDataset, FrameRecord


def _entry(cap_id, color=(120, 60, 30), size=None, deleted=False):
    return {"id": cap_id,
            "thumb": np.full((_TILE, _TILE, 3), color, np.uint8),
            "size": size, "deleted": deleted}


def test_strip_shape_and_thumbs_drawn():
    strip = render_recent_strip([_entry(1), _entry(2)], width=640)
    assert strip.shape == (_STRIP_H, 640, 3)
    # first tile area carries the entry colour, not the background
    tile = strip[4:4 + _TILE, 62:62 + _TILE]
    assert (tile == (120, 60, 30)).all(axis=-1).mean() > 0.9


def test_strip_shows_only_last_n():
    entries = [_entry(i, color=(i, i, i)) for i in range(1, RECENT_N + 4)]
    strip = render_recent_strip(entries, width=640)
    first_tile = strip[4:4 + _TILE, 62:62 + _TILE]
    # oldest surviving entry is len-RECENT_N+1, not #1
    want = len(entries) - RECENT_N + 1
    assert (first_tile == (want, want, want)).all(axis=-1).mean() > 0.9


def test_deleted_entry_marked_with_red_x():
    plain = render_recent_strip([_entry(7)], width=640)
    marked = render_recent_strip([_entry(7, deleted=True)], width=640)
    tile_p = plain[4:4 + _TILE, 62:62 + _TILE]
    tile_m = marked[4:4 + _TILE, 62:62 + _TILE]
    assert not np.array_equal(tile_p, tile_m)
    # X drawn in the reject red (BGR 60,60,235)
    assert ((tile_m == (60, 60, 235)).all(axis=-1)).sum() > 20


def test_thumb_placeholder_when_image_missing():
    t = _thumb(None)
    assert t.shape == (_TILE, _TILE, 3)
    assert (t == 70).all()


def test_recent_entries_from_db_reads_last_caps(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    db = CapDataset(tmp_path / "caps.db")
    try:
        for i in range(RECENT_N + 2):
            p = crops / f"cap_{i:04d}_f0.png"
            cv2.imwrite(str(p), np.full((32, 32, 3), 10 * i, np.uint8))
            db.add_cap((10 * i, 10 * i, 10 * i),
                       frames=[FrameRecord(0, str(p), rgb=(10 * i,) * 3)],
                       captured_at="2026-07-03T00:00:00", source="test",
                       diameter_mm=37.0 if i == 0 else 30.0)
        entries = recent_entries_from_db(db)
        assert len(entries) == RECENT_N
        assert entries[-1]["id"] == RECENT_N + 2      # newest cap last
        assert all(not e["deleted"] for e in entries)
        assert entries[-1]["size"] == "standard-26"
        assert entries[-1]["thumb"].shape == (_TILE, _TILE, 3)
    finally:
        db.close()


def test_recent_entries_survive_missing_crop_file(tmp_path):
    db = CapDataset(tmp_path / "caps.db")
    try:
        db.add_cap((5, 5, 5),
                   frames=[FrameRecord(0, str(tmp_path / "gone.png"), rgb=(5, 5, 5))],
                   captured_at="2026-07-03T00:00:00", source="test")
        entries = recent_entries_from_db(db)
        assert len(entries) == 1
        assert (entries[0]["thumb"] == 70).all()      # gray placeholder
    finally:
        db.close()
