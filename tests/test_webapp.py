import io

from fastapi.testclient import TestClient
from PIL import Image

from cap_mosaic.app.planner_designer import demo_image
from cap_mosaic.app.webapp.server import app

client = TestClient(app)


def _upload() -> str:
    buf = io.BytesIO()
    demo_image(96).save(buf, format="PNG")
    buf.seek(0)
    r = client.post("/upload", files={"file": ("demo.png", buf, "image/png")})
    assert r.status_code == 200
    return r.json()["id"]


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_returns_id_and_dims():
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), (10, 20, 30)).save(buf, format="PNG")
    buf.seek(0)
    r = client.post("/upload", files={"file": ("x.png", buf, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["width"] == 120 and body["height"] == 80
    assert abs(body["aspect"] - 1.5) < 1e-6


def test_estimate_from_size_has_caps_legibility_and_bom():
    iid = _upload()
    r = client.get("/estimate", params={"image_id": iid, "size_mm": 2000})
    assert r.status_code == 200
    b = r.json()
    assert b["caps_across"] > 0
    assert "legible" in b
    assert b["total_caps"] > 0
    assert isinstance(b["bom"], dict) and len(b["bom"]) > 0
    assert b["effective_colors"] <= b["colors_used"]
    assert 0 < b["apparent_pct"] <= 100
    # total_caps is the real (background-excluded) count == sum of the BOM,
    # never more than the full-panel area estimate.
    assert b["total_caps"] == sum(b["bom"].values())
    assert b["total_caps"] <= b["panel_caps"]


def test_bare_white_reduces_total_caps():
    # a white-bordered subject: holing the border must drop the buyable count
    buf = io.BytesIO()
    im = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(70, 130):
        for y in range(70, 130):
            im.putpixel((x, y), (200, 30, 30))
    im.save(buf, format="PNG")
    buf.seek(0)
    iid = client.post("/upload", files={"file": ("b.png", buf, "image/png")}).json()["id"]
    on = client.get("/estimate", params={"image_id": iid, "size_mm": 2000, "bare_white": True}).json()
    off = client.get("/estimate", params={"image_id": iid, "size_mm": 2000, "bare_white": False}).json()
    assert on["holes"] > 0
    assert on["total_caps"] < off["total_caps"]


def test_estimate_reports_thin_features_and_thicken_reduces_them():
    # white image with a 1-cap-wide dark cross
    buf = io.BytesIO()
    im = Image.new("RGB", (200, 200), (245, 245, 245))
    for i in range(200):
        for w in range(96, 104):
            im.putpixel((w, i), (20, 20, 20))
            im.putpixel((i, w), (20, 20, 20))
    im.save(buf, format="PNG")
    buf.seek(0)
    iid = client.post("/upload", files={"file": ("cross.png", buf, "image/png")}).json()["id"]
    plain = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    thick = client.get("/estimate", params={"image_id": iid, "size_mm": 2000, "thicken": True}).json()
    assert plain["thin_features"] > 0
    assert "thin_hint" in plain
    assert thick["thin_features"] < plain["thin_features"]


def test_estimate_preset_uses_curated_palette():
    iid = _upload()
    b = client.get("/estimate", params={"image_id": iid, "size_mm": 3000, "preset": "portrait"}).json()
    # portrait preset has 6 tones; used colours never exceed that
    assert b["colors_used"] <= 6


def test_estimate_reports_minimal_size_and_closest_distance():
    iid = _upload()
    b = client.get("/estimate", params={"image_id": iid, "size_mm": 3000}).json()
    assert b["min_size_m"] > 0
    # minimal size == legibility floor in metres (floor caps * 32 mm)
    assert abs(b["min_size_m"] - b["min_caps_across"] * 32 / 1000) < 0.01
    # closest reading distance == the blend (min) distance
    assert abs(b["closest_distance_m"] - b["min_distance_m"]) < 0.01


def test_estimate_from_distance_has_size_and_read_quality():
    iid = _upload()
    r = client.get("/estimate", params={"image_id": iid, "distance_m": 6.0})
    assert r.status_code == 200
    b = r.json()
    assert b["width_mm"] > 0
    assert b["read_quality"] in ("caps", "reads", "smooth")


def test_simulate_returns_png():
    iid = _upload()
    r = client.get("/simulate", params={"image_id": iid, "distance_m": 6.0})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 100


def test_simulate_output_is_the_fixed_frame_size():
    from cap_mosaic.app.webapp.server import _FRAME_PX

    iid = _upload()
    r = client.get("/simulate", params={"image_id": iid, "distance_m": 6.0})
    img = Image.open(io.BytesIO(r.content))
    assert img.size == _FRAME_PX


def test_simulate_is_fast_when_warm():
    import time

    iid = _upload()
    p = {"image_id": iid, "distance_m": 6.0}
    client.get("/simulate", params=p)  # warm the plan + library caches
    t0 = time.perf_counter()
    client.get("/simulate", params=p)
    dt_ms = (time.perf_counter() - t0) * 1000
    print(f"warm /simulate: {dt_ms:.0f} ms")
    assert dt_ms < 300


def test_crop_creates_a_smaller_image_and_image_endpoint_serves_it():
    iid = _upload()
    before = client.get("/image", params={"image_id": iid})
    assert before.status_code == 200 and before.headers["content-type"] == "image/png"
    w0 = Image.open(io.BytesIO(before.content)).width
    r = client.get("/crop", params={"image_id": iid, "x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75})
    assert r.status_code == 200
    b = r.json()
    assert b["id"] != iid
    cropped = Image.open(io.BytesIO(client.get("/image", params={"image_id": b["id"]}).content))
    assert cropped.width < w0  # region is a subset of the original


def test_crop_rejects_tiny_selection():
    iid = _upload()
    r = client.get("/crop", params={"image_id": iid, "x0": 0.5, "y0": 0.5, "x1": 0.501, "y1": 0.501})
    assert r.status_code == 400


def test_simulate_accepts_board_colour_and_real_only():
    iid = _upload()
    r = client.get("/simulate", params={"image_id": iid, "distance_m": 6.0,
                                        "bg_color": "#101820", "real_only": True})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_inventory_report_have_need_short(tmp_path, monkeypatch):
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for _ in range(3):
            db.add_cap((205, 25, 25), captured_at="t")  # ~red, within dE 12
        db.add_cap((30, 60, 200), captured_at="t")       # blue, far from red
    monkeypatch.setattr(server, "_DB", dbp)

    buf = io.BytesIO()
    Image.new("RGB", (120, 120), (200, 30, 30)).save(buf, format="PNG")
    buf.seek(0)
    iid = client.post("/upload", files={"file": ("r.png", buf, "image/png")}).json()["id"]
    b = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                        "inventory": True}).json()
    assert "inventory" in b
    row = next(iter(b["inventory"].values()))          # the single red BOM colour
    assert row["have"] == 3                             # 3 red caps match; blue doesn't
    assert row["short"] == row["need"] - 3
    assert b["inventory_totals"] == {"owned": 4, "have": 3, "need": row["need"]}


def test_critique_returns_score_and_recommendations():
    iid = _upload()
    b = client.get("/critique", params={"image_id": iid}).json()
    assert 0 <= b["score"] <= 100
    assert b["verdict"] in ("great", "good", "tricky", "poor")
    assert b["tips"] and b["recommend"]["min_size_m"] > 0


def test_capmap_returns_pdf_and_png():
    iid = _upload()
    pdf = client.get("/capmap", params={"image_id": iid, "size_mm": 1500, "format": "pdf"})
    png = client.get("/capmap", params={"image_id": iid, "size_mm": 1500, "format": "png"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"


def test_target_is_frame_sized_and_differs_from_simulate():
    from cap_mosaic.app.webapp.server import _FRAME_PX

    iid = _upload()
    p = {"image_id": iid, "size_mm": 2500, "distance_m": 6.0}
    tgt = client.get("/target", params=p)
    sim = client.get("/simulate", params=p)
    assert tgt.status_code == 200 and tgt.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(tgt.content)).size == _FRAME_PX  # same framing
    assert tgt.content != sim.content                              # original != caps


def test_simulate_dither_changes_output():
    iid = _upload()
    off = client.get("/simulate", params={"image_id": iid, "size_mm": 2000, "dither": False}).content
    on = client.get("/simulate", params={"image_id": iid, "size_mm": 2000, "dither": True}).content
    assert off != on and len(on) > 100


def test_simulate_highlight_isolates_a_colour():
    iid = _upload()
    b = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    hexcol = next(iter(b["bom"]))  # a colour that's actually in the plan
    # sharp view (no distance) so ghosting is visible; highlighting changes output
    plain = client.get("/simulate", params={"image_id": iid, "size_mm": 2000}).content
    hi = client.get("/simulate", params={"image_id": iid, "size_mm": 2000,
                                         "highlight": hexcol}).content
    assert hi != plain and len(hi) > 100


def test_unknown_image_id_404():
    r = client.get("/estimate", params={"image_id": "nope", "size_mm": 1000})
    assert r.status_code == 404


def test_index_and_static_served():
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="dropzone"' in r.text and 'id="size"' in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
