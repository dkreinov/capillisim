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


def test_scanner_launch_spawns_the_capture_app(monkeypatch):
    import subprocess

    spawned = {}

    def fake_popen(args, **kw):
        spawned["args"] = args
        spawned["kw"] = kw
        class P:  # noqa: N801 - stand-in for a healthy long-running scanner
            pid = 4242
            stdout = None
            def poll(self):
                return None
        return P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    r = client.post("/scanner/launch", params={"camera": 2})
    assert r.status_code == 200 and r.json()["launched"] is True
    joined = " ".join(spawned["args"])
    assert "cap_mosaic.app.cap_capture" in joined and "--auto" in joined
    assert "--camera 2" in joined


def test_scanner_launch_reports_camera_failure(monkeypatch):
    import io as _io
    import subprocess

    def fake_popen(args, **kw):
        class P:  # noqa: N801 - a scanner that dies immediately
            pid = 4243
            returncode = 1
            stdout = _io.StringIO("could not open camera index 0\n")
            def poll(self):
                return 1
        return P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    b = client.post("/scanner/launch").json()
    assert b["launched"] is False
    assert "could not open camera" in b["error"]


def test_pattern_and_palette_prompt_from_stock(tmp_path, monkeypatch):
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for _ in range(9):
            db.add_cap((200, 30, 30), captured_at="t")
        for _ in range(7):
            db.add_cap((40, 70, 190), captured_at="t")
    monkeypatch.setattr(server, "_DB", dbp)

    ids = set()
    for kind in ("gradient", "bullseye", "sunburst"):
        b = client.get("/pattern", params={"kind": kind}).json()
        assert b["caps"] == 16                       # every owned cap exactly once
        assert b["id"] not in ids                    # each pattern is a new image
        ids.add(b["id"])
        img = client.get("/image", params={"image_id": b["id"]})
        assert img.status_code == 200
    assert client.get("/pattern", params={"kind": "plaid"}).status_code == 400

    p = client.get("/palette_prompt").json()
    assert p["prompt"].count("#") >= 2 and "16 tiles" in p["prompt"]


def test_from_my_caps_plans_within_stock(tmp_path, monkeypatch):
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for _ in range(10):
            db.add_cap((200, 30, 30), captured_at="t")   # 10 red caps
        for _ in range(10):
            db.add_cap((40, 70, 190), captured_at="t")   # 10 blue caps
    monkeypatch.setattr(server, "_DB", dbp)

    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (150, 40, 60)).save(buf, format="PNG")
    buf.seek(0)
    iid = client.post("/upload", files={"file": ("s.png", buf, "image/png")}).json()["id"]
    b = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                        "from_my_caps": True}).json()
    # the plan can never place more caps than owned; readout reports the spend
    assert b["total_caps"] <= 20
    assert b["stock_used"]["owned"] == 20
    assert b["stock_used"]["used"] == b["total_caps"]
    # simulate accepts the same flag
    r = client.get("/simulate", params={"image_id": iid, "size_mm": 2000,
                                        "from_my_caps": True})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_caps_count_reports_inventory_size(tmp_path, monkeypatch):
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for i in range(5):
            db.add_cap((10 * i, 20, 30), captured_at="t")
    monkeypatch.setattr(server, "_DB", dbp)
    assert client.get("/caps_count").json() == {"count": 5}
    monkeypatch.setattr(server, "_DB", tmp_path / "missing.db")
    assert client.get("/caps_count").json() == {"count": 0}


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


def test_critique_llm_merges_qwen_verdict(monkeypatch):
    from cap_mosaic.app import llm_judge

    monkeypatch.setattr(llm_judge, "qwen_judge",
                        lambda img: {"score": 88, "verdict": "great",
                                     "tips": ["bold"], "better_subject": "",
                                     "actions": [{"set": "colors", "value": 6}],
                                     "model": "qwen3-vl-plus"})
    iid = _upload()
    plain = client.get("/critique", params={"image_id": iid}).json()
    assert "llm" not in plain                       # opt-in only
    b = client.get("/critique", params={"image_id": iid, "llm": True}).json()
    assert b["llm"]["score"] == 88 and b["llm"]["verdict"] == "great"
    assert b["llm"]["actions"] == [{"set": "colors", "value": 6}]  # actions flow through
    assert b["score"] == plain["score"]             # heuristic part unchanged


def test_simplify_stores_edited_image_under_new_id(monkeypatch):
    from cap_mosaic.app import ai_edit

    def fake_simplify(img, instructions):
        assert "bottle-cap" in instructions        # default instruction used
        return Image.new("RGB", (40, 30), (1, 2, 3))  # a recognizably new image

    monkeypatch.setattr(ai_edit, "ai_simplify", fake_simplify)
    iid = _upload()
    b = client.get("/simplify", params={"image_id": iid}).json()
    assert b["id"] != iid                          # stored as a NEW image
    served = Image.open(io.BytesIO(client.get("/image", params={"image_id": b["id"]}).content))
    assert served.size == (40, 30) and served.getpixel((0, 0)) == (1, 2, 3)
    # the original is still intact under its old id
    orig = Image.open(io.BytesIO(client.get("/image", params={"image_id": iid}).content))
    assert orig.size != (40, 30)


def test_palettes_returns_a_comparison_sheet():
    iid = _upload()
    r = client.get("/palettes", params={"image_id": iid, "size_mm": 1500})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    w, h = Image.open(io.BytesIO(r.content)).size
    assert w >= 600 and h >= 300  # a 2x2 grid of labelled thumbnails


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


# --- click-a-colour-to-background: /pick + bg_colors/bg_seeds ---

def _upload_two_tone() -> str:
    """Left half red, right half blue - crisp colour regions for pick/flood."""
    im = Image.new("RGB", (200, 200), (200, 30, 30))
    for x in range(100, 200):
        for y in range(200):
            im.putpixel((x, y), (30, 30, 200))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    return client.post("/upload", files={"file": ("t.png", buf, "image/png")}).json()["id"]


def _bom_sides(iid):
    """(red pick, blue pick) as quantized by the plan, via /pick on each side."""
    l = client.get("/pick", params={"image_id": iid, "size_mm": 2000,
                                    "fx": 0.25, "fy": 0.5}).json()
    r = client.get("/pick", params={"image_id": iid, "size_mm": 2000,
                                    "fx": 0.75, "fy": 0.5}).json()
    assert l["hit"] and r["hit"]
    return l, r


def test_pick_returns_cell_colour_sharp():
    iid = _upload_two_tone()
    l, r = _bom_sides(iid)
    lr, lg, lb = (int(l["hex"][i:i + 2], 16) for i in (1, 3, 5))
    rr, rg, rb = (int(r["hex"][i:i + 2], 16) for i in (1, 3, 5))
    assert lr > lb and rb > rr  # left reads red, right reads blue
    # returned fx/fy are the cell CENTRE: picking there again hits the same cell
    again = client.get("/pick", params={"image_id": iid, "size_mm": 2000,
                                        "fx": l["fx"], "fy": l["fy"]}).json()
    assert (again["row"], again["col"]) == (l["row"], l["col"])


def test_pick_letterbox_inverse_roundtrip():
    from cap_mosaic.app.planner_designer import framed_box
    from cap_mosaic.app.webapp import server as srv

    iid = _upload_two_tone()
    # letterbox margin at a far distance misses
    m = client.get("/pick", params={"image_id": iid, "size_mm": 2000,
                                    "distance_m": 12.0, "fx": 0.02, "fy": 0.5}).json()
    assert m == {"hit": False}
    # forward-map a known cell centre through the render math -> /pick inverts it
    cell = client.get("/pick", params={"image_id": iid, "size_mm": 2000,
                                       "fx": 0.3, "fy": 0.4}).json()
    img = srv._IMAGES[iid]
    res = srv._solve(img, iid, "picture", 32.0, 2000.0, None)
    plan = srv._plan(iid, img, res["caps_across"], 12)
    capped = max(1, min(res["caps_across"], srv._MAX_CAPS_ACROSS))
    px_per_cap = max(6, min(22, srv._SIM_WIDTH_PX // capped))
    ppm = px_per_cap / plan.cap_diameter_mm
    mosaic_px = (max(1, round(plan.width_mm * ppm)),
                 max(1, round(plan.height_mm * ppm)))
    x0, y0, w, h = framed_box(mosaic_px, res["width_mm"], 6.0, srv._FRAME_PX)
    fxf = (cell["fx"] * w + x0) / srv._FRAME_PX[0]
    fyf = (cell["fy"] * h + y0) / srv._FRAME_PX[1]
    back = client.get("/pick", params={"image_id": iid, "size_mm": 2000,
                                       "distance_m": 6.0, "fx": fxf, "fy": fyf}).json()
    assert back["hit"] and (back["row"], back["col"]) == (cell["row"], cell["col"])


def test_bg_colors_hole_the_colour_and_cache_stays_pure():
    iid = _upload_two_tone()
    l, _ = _bom_sides(iid)
    red = l["hex"]
    # FIRST request applies the exclusion (overlays the freshly cached plan)...
    ex = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                         "bg_colors": red.lstrip("#")}).json()
    # ...then the plain request must see the untouched cached plan
    base = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    n = base["bom"][red]
    assert red not in ex["bom"]
    assert ex["holes"] == base["holes"] + n
    assert ex["total_caps"] == base["total_caps"] - n
    assert base["holes"] == 0  # saturated two-tone: nothing bare-white, no mutation


def test_bg_colors_shrink_the_shopping_list(tmp_path, monkeypatch):
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for _ in range(10):
            db.add_cap((200, 30, 30), captured_at="t")
    monkeypatch.setattr(server, "_DB", dbp)

    iid = _upload_two_tone()
    l, _ = _bom_sides(iid)
    red = l["hex"]
    base = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                           "inventory": True}).json()
    assert base["inventory"][red]["have"] > 0
    ex = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                         "inventory": True,
                                         "bg_colors": red.lstrip("#")}).json()
    assert red not in ex["inventory"]
    assert ex["inventory_totals"]["need"] < base["inventory_totals"]["need"]


def test_bg_seed_flood_stops_at_colour_boundary():
    iid = _upload_two_tone()
    l, r = _bom_sides(iid)
    base = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    seed = "{}:{}:{}".format(l["fx"], l["fy"], l["hex"].lstrip("#"))
    ex = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                         "bg_seeds": seed}).json()
    assert ex["bom"].get(r["hex"]) == base["bom"][r["hex"]]  # blue untouched
    assert ex["bom"].get(l["hex"], 0) <= base["bom"][l["hex"]] * 0.05  # red gone
    assert ex["holes"] > base["holes"]


def test_bg_seed_confined_to_connected_region():
    # two separated red squares on blue: seeding one leaves the other standing
    im = Image.new("RGB", (200, 200), (30, 30, 200))
    for x0 in (10, 130):
        for x in range(x0, x0 + 60):
            for y in range(70, 130):
                im.putpixel((x, y), (200, 30, 30))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    iid = client.post("/upload", files={"file": ("s.png", buf, "image/png")}).json()["id"]
    left = client.get("/pick", params={"image_id": iid, "size_mm": 2000,
                                       "fx": 0.2, "fy": 0.5}).json()
    base = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    n_red = base["bom"][left["hex"]]
    seed = "{}:{}:{}".format(left["fx"], left["fy"], left["hex"].lstrip("#"))
    ex = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                         "bg_seeds": seed}).json()
    remaining = ex["bom"].get(left["hex"], 0)
    assert 0 < remaining < n_red  # one island removed, the other survives


def test_bg_seed_with_stale_hex_is_ignored():
    iid = _upload_two_tone()
    l, _ = _bom_sides(iid)
    base = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    stale = "{}:{}:00ff00".format(l["fx"], l["fy"])
    ex = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                         "bg_seeds": stale}).json()
    assert ex["bom"] == base["bom"] and ex["holes"] == base["holes"]


def test_simulate_and_capmap_accept_bg_params():
    iid = _upload_two_tone()
    l, _ = _bom_sides(iid)
    p = {"image_id": iid, "size_mm": 2000, "distance_m": 6.0}
    plain = client.get("/simulate", params=p)
    holed = client.get("/simulate", params={**p, "bg_colors": l["hex"].lstrip("#")})
    assert plain.status_code == holed.status_code == 200
    assert plain.content != holed.content
    im = Image.open(io.BytesIO(holed.content))
    assert im.size == (900, 650)  # frame size intact
    r = client.get("/capmap", params={"image_id": iid, "size_mm": 2000,
                                      "bg_colors": l["hex"].lstrip("#")})
    assert r.status_code == 200
    bad = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                          "bg_colors": "zz"})
    assert bad.status_code == 400


def test_pick_reports_exclusion_cause():
    iid = _upload_two_tone()
    l, _ = _bom_sides(iid)
    by_color = client.get("/pick", params={
        "image_id": iid, "size_mm": 2000, "fx": l["fx"], "fy": l["fy"],
        "bg_colors": l["hex"].lstrip("#")}).json()
    assert by_color["excluded_by"] == "color" and by_color["seed_index"] is None
    seed = "{}:{}:{}".format(l["fx"], l["fy"], l["hex"].lstrip("#"))
    by_seed = client.get("/pick", params={
        "image_id": iid, "size_mm": 2000, "fx": l["fx"], "fy": l["fy"],
        "bg_seeds": seed}).json()
    assert by_seed["excluded_by"] == "seed" and by_seed["seed_index"] == 0
    # a bare-white hole reports bare (white border image, bare_white default on)
    im = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(70, 130):
        for y in range(70, 130):
            im.putpixel((x, y), (30, 120, 60))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    wid = client.post("/upload", files={"file": ("w.png", buf, "image/png")}).json()["id"]
    border = client.get("/pick", params={"image_id": wid, "size_mm": 2000,
                                         "fx": 0.05, "fy": 0.05}).json()
    assert border["hit"] and border["bare"] is True


# --- non-rectangular shapes: shape= / poly= on the plan pipeline ---

def test_shape_circle_reduces_caps_and_bom_stays_consistent():
    iid = _upload()
    rect = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    circ = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                           "shape": "circle"}).json()
    assert circ["panel_caps"] < rect["panel_caps"]
    assert circ["total_caps"] < rect["total_caps"]
    assert circ["total_caps"] == sum(circ["bom"].values())
    assert circ["panel_caps"] == circ["total_caps"] + circ["holes"]
    # cache distinctness: rect numbers unchanged after the circle request
    rect2 = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    assert rect2["total_caps"] == rect["total_caps"]


def test_poly_triangle_works_and_bad_polys_400():
    iid = _upload()
    rect = client.get("/estimate", params={"image_id": iid, "size_mm": 2000}).json()
    tri = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                          "poly": "0.1,0.9;0.5,0.1;0.9,0.9"}).json()
    assert 0 < tri["total_caps"] < rect["total_caps"]
    assert client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                           "poly": "x"}).status_code == 400
    assert client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                           "poly": "0.1,0.1;0.9,0.9"}).status_code == 400
    # a sliver polygon leaves no cell centres inside -> 400, not a crash
    r = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                        "poly": "0.001,0.001;0.002,0.001;0.002,0.002"})
    assert r.status_code == 400


def test_shape_flows_to_simulate_capmap_and_pick():
    iid = _upload()
    p = {"image_id": iid, "size_mm": 2000}
    rect_map = client.get("/capmap", params=p)
    circ_map = client.get("/capmap", params={**p, "shape": "circle"})
    assert rect_map.status_code == circ_map.status_code == 200
    assert rect_map.content != circ_map.content
    sim = client.get("/simulate", params={**p, "shape": "heart"})
    assert sim.status_code == 200
    # pick at the centre hits a cell; a frame corner (outside the circle) misses
    hit = client.get("/pick", params={**p, "shape": "circle",
                                      "fx": 0.5, "fy": 0.5}).json()
    miss = client.get("/pick", params={**p, "shape": "circle",
                                       "fx": 0.02, "fy": 0.02}).json()
    assert hit["hit"] is True and miss == {"hit": False}


def test_shape_with_own_caps_fits_within_stock(tmp_path, monkeypatch):
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for _ in range(30):
            db.add_cap((200, 30, 30), captured_at="t")
        for _ in range(30):
            db.add_cap((40, 70, 190), captured_at="t")
    monkeypatch.setattr(server, "_DB", dbp)

    buf = io.BytesIO()
    im = Image.new("RGB", (200, 200), (150, 40, 60))
    im.save(buf, format="PNG")
    buf.seek(0)
    iid = client.post("/upload", files={"file": ("o.png", buf, "image/png")}).json()["id"]
    b = client.get("/estimate", params={"image_id": iid, "size_mm": 2000,
                                        "from_my_caps": True,
                                        "shape": "circle"}).json()
    assert 0 < b["total_caps"] <= 60
    assert b["panel_caps"] == b["total_caps"] + b["holes"]


# --- sized/unlimited patterns + gallery endpoints ---

def test_sized_pattern_reports_cells_and_missing(tmp_path, monkeypatch):
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for _ in range(9):
            db.add_cap((200, 30, 30), captured_at="t")
        for _ in range(7):
            db.add_cap((40, 70, 190), captured_at="t")
    monkeypatch.setattr(server, "_DB", dbp)

    b = client.get("/pattern", params={"kind": "waves", "width_mm": 640,
                                       "height_mm": 480}).json()
    assert b["cells"] > 16                      # frame is bigger than the stock
    assert b["caps"] == 16                      # every owned cap placed once
    assert b["missing"] == b["cells"] - b["caps"]
    # unlimited: same frame, no missing caps
    u = client.get("/pattern", params={"kind": "waves", "width_mm": 640,
                                       "height_mm": 480, "unlimited": True}).json()
    assert u["missing"] == 0 and u["caps"] == u["cells"] == b["cells"]
    # shaped pattern drops cells
    c = client.get("/pattern", params={"kind": "waves", "width_mm": 640,
                                       "height_mm": 480, "unlimited": True,
                                       "shape": "circle"}).json()
    assert 0 < c["cells"] < b["cells"]
    # dims must come in pairs; shape needs dims
    assert client.get("/pattern", params={"kind": "waves",
                                          "width_mm": 640}).status_code == 400
    assert client.get("/pattern", params={"kind": "waves",
                                          "shape": "circle"}).status_code == 400


def test_pattern_unlimited_without_db(monkeypatch, tmp_path):
    from cap_mosaic.app.webapp import server

    monkeypatch.setattr(server, "_DB", tmp_path / "absent.db")
    assert client.get("/pattern", params={"kind": "gradient"}).status_code == 404
    b = client.get("/pattern", params={"kind": "gradient", "width_mm": 480,
                                       "height_mm": 480, "unlimited": True})
    assert b.status_code == 200 and b.json()["missing"] == 0


def test_pattern_kinds_and_thumbs(monkeypatch, tmp_path):
    from cap_mosaic.app.webapp import server

    kinds = client.get("/pattern_kinds").json()
    assert set(kinds["kinds"]) >= {"gradient", "bullseye", "sunburst", "waves",
                                   "stripes", "diamonds", "mandala", "swirl",
                                   "arcs", "patchwork", "rays", "medallions",
                                   "rosettes", "scales"}
    assert kinds["blurbs"]["mandala"]
    monkeypatch.setattr(server, "_DB", tmp_path / "absent.db")
    r1 = client.get("/pattern_thumb", params={"kind": "mandala"})
    assert r1.status_code == 200
    assert r1.headers["content-type"] == "image/png"
    assert "max-age" in r1.headers.get("cache-control", "")
    r2 = client.get("/pattern_thumb", params={"kind": "mandala"})
    assert r2.content == r1.content             # served from the module cache
    assert client.get("/pattern_thumb", params={"kind": "plaid"}).status_code == 400


# --- AI pattern (text-to-image, mocked) ---

def test_ai_pattern_generates_and_stores(tmp_path, monkeypatch):
    from cap_mosaic.app import ai_edit
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        for _ in range(5):
            db.add_cap((200, 30, 30), captured_at="t")
    monkeypatch.setattr(server, "_DB", dbp)

    seen = {}

    def fake_pattern(prompt, size="1328*1328", **kw):
        seen["prompt"], seen["size"] = prompt, size
        return Image.new("RGB", (640, 480), (180, 60, 40))

    monkeypatch.setattr(ai_edit, "ai_pattern", fake_pattern)
    r = client.get("/ai_pattern", params={"width_mm": 1600, "height_mm": 900})
    assert r.status_code == 200
    b = r.json()
    assert b["width"] == 640 and b["height"] == 480
    assert "#" in seen["prompt"] and "pattern" in seen["prompt"].lower()
    assert seen["size"] == "1664*928"          # widest supported aspect chosen
    # the stored id serves like any upload
    assert client.get("/image", params={"image_id": b["id"]}).status_code == 200


def test_ai_pattern_no_db_and_failure_paths(tmp_path, monkeypatch):
    from cap_mosaic.app import ai_edit
    from cap_mosaic.app.webapp import server
    from cap_mosaic.data.store import CapDataset

    monkeypatch.setattr(server, "_DB", tmp_path / "absent.db")
    assert client.get("/ai_pattern").status_code == 404

    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        db.add_cap((10, 10, 10), captured_at="t")
    monkeypatch.setattr(server, "_DB", dbp)

    def boom(prompt, **kw):
        raise RuntimeError("QWEEN_KEY not set")

    monkeypatch.setattr(ai_edit, "ai_pattern", boom)
    r = client.get("/ai_pattern")
    assert r.status_code == 502 and "QWEEN_KEY" in r.json()["detail"]


def test_t2i_size_for_picks_nearest_aspect():
    from cap_mosaic.app.ai_edit import t2i_size_for

    assert t2i_size_for(16 / 9) == "1664*928"
    assert t2i_size_for(1.0) == "1328*1328"
    assert t2i_size_for(9 / 16) == "928*1664"


def test_detail_render_is_higher_resolution():
    iid = _upload()
    small = client.get("/simulate", params={"image_id": iid, "size_mm": 2000})
    big = client.get("/simulate", params={"image_id": iid, "size_mm": 2000,
                                          "detail": True})
    ws = Image.open(io.BytesIO(small.content)).width
    wb = Image.open(io.BytesIO(big.content)).width
    assert wb > ws * 2                       # close-up budget ~4x the tile pixels
    # detail is a close-up concept: with a distance frame it changes nothing
    framed = client.get("/simulate", params={"image_id": iid, "size_mm": 2000,
                                             "distance_m": 6.0, "detail": True})
    assert Image.open(io.BytesIO(framed.content)).size == (900, 650)
