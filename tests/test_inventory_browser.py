"""The /inventory browser: list caps, serve crop thumbnails, mouse-delete."""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cap_mosaic.app.webapp import server
from cap_mosaic.app.webapp.server import app
from cap_mosaic.data.store import CapDataset, FrameRecord

client = TestClient(app)


@pytest.fixture()
def inv_db(tmp_path, monkeypatch):
    """A tiny cap DB (2 caps, one with a crop file) wired into the server."""
    crops = tmp_path / "crops"
    crops.mkdir()
    p = crops / "cap_0000_f0.png"
    # a cap face with internal detail (a bright logo) so the distance test has
    # something to wash out: near = logo visible, far = flat average
    face = np.full((48, 48, 3), 90, np.uint8)
    face[18:30, 18:30] = 230  # logo patch
    Image.fromarray(face).save(p)
    db = CapDataset(tmp_path / "caps.db")
    a = db.add_cap((10, 20, 30), frames=[FrameRecord(0, str(p), rgb=(10, 20, 30))],
                   captured_at="2026-07-04T00:00:00", source="test",
                   mosaic_rgb=(50, 60, 70), diameter_mm=30.2, crop_span_mm=37.8)
    b = db.add_cap((200, 10, 10), captured_at="2026-07-04T00:00:01", source="test",
                   diameter_mm=38.4)
    db.close()
    monkeypatch.setattr(server, "_DB", tmp_path / "caps.db")
    return {"a": a, "b": b, "crop": p, "db": tmp_path / "caps.db"}


def test_inventory_page_served():
    r = client.get("/inventory")
    assert r.status_code == 200
    assert "Cap inventory" in r.text


def test_inventory_lists_caps_newest_first(inv_db):
    r = client.get("/inventory/caps")
    assert r.status_code == 200
    caps = r.json()
    assert [c["id"] for c in caps] == [inv_db["b"], inv_db["a"]]
    a = caps[1]
    assert a["field"] == [10, 20, 30] and a["mosaic"] == [50, 60, 70]
    assert a["size_class"] == "standard-26" and a["has_crop"]
    assert caps[0]["size_class"] == "large-38" and not caps[0]["has_crop"]


def test_inventory_serves_crop_image(inv_db):
    r = client.get(f"/inventory/crop/{inv_db['a']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert client.get(f"/inventory/crop/{inv_db['b']}").status_code == 404  # no crop
    assert client.get("/inventory/crop/99999").status_code == 404


def test_inventory_delete_removes_row_and_files(inv_db):
    assert Path(inv_db["crop"]).exists()
    r = client.delete(f"/inventory/caps/{inv_db['a']}")
    assert r.status_code == 200 and r.json()["deleted"] == inv_db["a"]
    assert not Path(inv_db["crop"]).exists()          # crop file gone too
    with CapDataset(inv_db["db"]) as db:
        assert [c.id for c in db.caps()] == [inv_db["b"]]
    assert client.delete(f"/inventory/caps/{inv_db['a']}").status_code == 404


def test_inventory_distance_test_constant_frame(inv_db):
    import io as _io

    near = client.get(f"/inventory/test/{inv_db['a']}?distance_m=0.5")
    far = client.get(f"/inventory/test/{inv_db['a']}?distance_m=12.0")
    assert near.status_code == 200 and far.status_code == 200
    ni = Image.open(_io.BytesIO(near.content))
    fi = Image.open(_io.BytesIO(far.content))
    # the coloured area never shrinks into board: the frame size is constant
    assert ni.size == fi.size == (640, 420)
    # ...but the renders differ (more, smaller caps far away) — a real zoom-out
    assert near.content != far.content


def test_far_view_converges_to_mosaic_colour_in_linear_light():
    # the fix: blending must be in LINEAR light. A navy+white cap's sRGB-space
    # mean is far from its linear mean (the stored mosaic value); if the wall
    # blended in sRGB the far view would be the wrong colour. On a board set to
    # the cap's own colour (grout invisible), the far tiled half must match the
    # mosaic colour it was built from.
    from cap_mosaic.app.webapp.server import _render_wall, _MAX_CAPS

    tile = 32
    cap = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
    from PIL import ImageDraw

    dr = ImageDraw.Draw(cap)
    dr.ellipse([0, 0, tile - 1, tile - 1], fill=(10, 20, 90, 255))   # navy field
    dr.ellipse([9, 9, 22, 22], fill=(240, 240, 240, 255))            # white logo
    # the cap's own linear-light mean = the "mosaic" colour it should read as
    a = np.asarray(cap).astype(np.float32) / 255.0
    inside = a[..., 3] > 0.5
    lin = ((a[inside, :3]) ** 2.4).mean(0)  # rough sRGB->linear->mean
    mosaic = tuple(int(round((v ** (1 / 2.4)) * 255)) for v in lin)

    far = np.asarray(_render_wall(cap, _MAX_CAPS, (640, 420), mosaic, mosaic))
    left = far[:, :320].reshape(-1, 3).mean(0)
    # board == mosaic, so grout is invisible; far tiled half ~= mosaic colour.
    # (A buggy sRGB blend would land ~40 levels darker.)
    assert np.abs(left - np.array(mosaic)).max() < 14, (left, mosaic)


def test_caps_get_smaller_and_more_with_distance():
    # stepping back fits more caps into the same window (caps_across ∝ distance)
    from cap_mosaic.app.webapp.server import _caps_across_for, _BASE_CAPS, _MAX_CAPS

    assert _caps_across_for(0.5) == _BASE_CAPS          # reference distance
    assert _caps_across_for(4.0) > _caps_across_for(1.0)  # monotone increasing
    assert _caps_across_for(1.0) > _caps_across_for(0.5)
    assert _caps_across_for(999.0) == _MAX_CAPS         # clamped (stays cap texture)


def test_inventory_distance_test_selectable_background(inv_db):
    # the board colour shows through the gaps between caps, so two different
    # boards must produce visibly different renders at a close distance
    white = client.get(f"/inventory/test/{inv_db['a']}?distance_m=0.5&bg=%23ffffff")
    dark = client.get(f"/inventory/test/{inv_db['a']}?distance_m=0.5&bg=%23103050")
    assert white.content != dark.content


def test_inventory_distance_test_404s(inv_db):
    assert client.get(f"/inventory/test/{inv_db['b']}").status_code == 404  # no crop
    assert client.get("/inventory/test/99999").status_code == 404


def test_wall_hex_packs_caps_close():
    # glued caps touch: board must show ONLY in the small curved gaps between
    # circles (thin grout), never as full margins
    from cap_mosaic.app.webapp.server import _render_wall

    tile = 48
    disc = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(disc).ellipse([0, 0, tile - 1, tile - 1], fill=(40, 90, 40, 255))
    frame = (640, 420)
    wall = _render_wall(disc, caps_left=frame[0] // 2 // tile, frame=frame,
                        board=(255, 0, 255), mosaic=(10, 10, 10))
    px = np.asarray(wall)
    half = frame[0] // 2
    interior = px[40:frame[1] - 40, 40:half - 40]  # skip ragged top/edges
    board_frac = ((interior == [255, 0, 255]).all(axis=2)).mean()
    assert board_frac < 0.06, board_frac                      # thin grout only
    right = px[:, half + 4:]
    assert ((right == [10, 10, 10]).all(axis=2)).mean() > 0.99  # clean solid half


def test_cap_cutout_shrinks_past_printed_circle():
    # Hough locks onto the printed placement circle; the cutout must walk in
    # to the real cap edge or every tile carries a white card ring
    import cv2
    from cap_mosaic.app.cap_crop import cap_cutout

    img = np.full((128, 128, 3), 245, np.uint8)
    cv2.circle(img, (64, 64), 55, (150, 150, 150), 2)    # printed circle
    cv2.circle(img, (64, 64), 34, (30, 40, 120), -1)     # the actual cap
    cut = np.asarray(cap_cutout(img, 48))
    # the ring just inside the cutout edge must be cap, not card-white
    yy, xx = np.ogrid[:48, :48]
    d2 = (xx - 24) ** 2 + (yy - 24) ** 2
    band = (d2 >= 20 ** 2) & (d2 <= 23 ** 2)
    edge = cut[band]
    white = (edge[:, :3] >= 215).all(axis=1) & (edge[:, 3] > 0)
    assert white.mean() < 0.2, white.mean()


def test_inventory_empty_without_db(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DB", tmp_path / "absent.db")
    assert client.get("/inventory/caps").json() == []
    assert client.delete("/inventory/caps/1").status_code == 404
