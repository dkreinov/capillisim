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


def test_unknown_image_id_404():
    r = client.get("/estimate", params={"image_id": "nope", "size_mm": 1000})
    assert r.status_code == 404


def test_index_and_static_served():
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="dropzone"' in r.text and 'id="size"' in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
