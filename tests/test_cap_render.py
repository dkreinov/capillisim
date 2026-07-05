import numpy as np

from cap_mosaic.app import cap_render
from cap_mosaic.app.planner_designer import demo_image, plan_from_image, simulate_distance
from cap_mosaic.core.geometry import Cap, grid_for_caps_across


def _hf_energy(img):
    a = np.asarray(img.convert("L"), float)
    lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return lap.var()


def _plan():
    img = demo_image(128)
    grid = grid_for_caps_across(8, aspect_ratio=1.0, cap=Cap())
    return plan_from_image(img, grid)


def test_build_library_makes_variants_per_colour():
    colors = [(200, 30, 30), (30, 80, 160), (230, 200, 70)]
    lib = cap_render.build_library(colors, db_path=None, size=48, variants=3)
    assert len(lib) == 9  # 3 colours x 3 variants for a diverse mosaic
    # variants of a colour differ (shade jitter / different logos)
    reds = [c for c in lib if abs(c.rgb[0] - 200) < 40 and c.rgb[1] < 90]
    assert len({c.rgb for c in reds}) >= 2


def test_render_produces_sized_canvas():
    plan = _plan()
    colors = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    lib = cap_render.build_library(colors, size=48)
    mosaic = cap_render.render_mosaic_caps(plan, lib, px_per_cap=24)
    assert mosaic.size[0] > 0 and mosaic.size[1] > 0
    assert mosaic.mode == "RGB"


def test_gaps_between_caps_show_the_board_colour():
    import numpy as np

    plan = _plan()
    colors = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    lib = cap_render.build_library(colors, size=48)
    board = (12, 200, 30)  # a distinctive board colour
    img = np.asarray(cap_render.render_mosaic_caps(plan, lib, px_per_cap=24, background=board))
    # the round caps leave interstitial gaps that must show the board colour,
    # not the cap colour — so the board colour is present in the interior
    interior = img[24:-24, 24:-24]
    board_hits = (np.abs(interior.astype(int) - np.array(board)) <= 6).all(2).mean()
    assert board_hits > 0.01


def test_real_only_uses_photographed_caps_when_available():
    from PIL import Image as PILImage
    from cap_mosaic.app.fake_caps import CapImage

    plan = _plan()
    # a library with one procedural cap and one tagged "real" of the same colour
    rgb = (200, 60, 60)
    proc = cap_render.build_library([rgb], size=32, variants=1)[0]
    real = CapImage(rgb, PILImage.new("RGBA", (32, 32), (*rgb, 255)), real=True)
    # real_only must not raise and must render (it filters to the real cap)
    out = cap_render.render_mosaic_caps(plan, [proc, real], px_per_cap=16, real_only=True)
    assert out.size[0] > 0


def _cap_crop_file(path, cx=70, cy=60, r=34, color=(40, 60, 200), n=128):
    """A synthetic dataset crop: off-centre cap disc (BGR-ish colours via PIL RGB)."""
    import numpy as np
    from PIL import Image as PILImage, ImageDraw

    img = PILImage.new("RGB", (n, n), (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(30, 30, 30), width=3)
    img.save(path)
    return path


def test_real_caps_use_geometry_and_disk_cache(tmp_path):
    import numpy as np
    from cap_mosaic.data.store import CapDataset

    crop = _cap_crop_file(str(tmp_path / "cap_0000_f0.png"))
    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        from cap_mosaic.data.store import FrameRecord
        # geometry: 30mm cap in a 56.25mm crop -> radius_frac (30/56.25)/2 ~ 0.267 -> r ~34px
        db.add_cap((200, 40, 40), captured_at="t",
                   frames=[FrameRecord(frame_index=0, path=crop, rgb=(200, 40, 40))],
                   diameter_mm=30.0, crop_span_mm=56.25)

    caps = cap_render._real_caps(str(dbp), 64, dbp.stat().st_mtime)
    assert len(caps) == 1
    a = np.asarray(caps[0].image)
    # centred + tight: middle is the cap colour (opaque blue), corners transparent
    assert a[32, 32, 3] == 255 and a[32, 32, 2] > 150 and a[32, 32, 0] < 120
    assert a[1, 1, 3] == 0 and a[62, 62, 3] == 0
    # a ring just inside the edge must be CAP, not white card padding
    edge = a[32, 6]
    assert edge[3] == 255 and not (edge[:3] > 235).all()

    # a persistent cutout landed on disk next to the db
    cache = list((tmp_path / "cutouts").glob("*.png"))
    assert len(cache) == 1
    cap_render._real_caps.cache_clear()
    caps2 = cap_render._real_caps(str(dbp), 64, dbp.stat().st_mtime)  # served from disk
    assert np.array_equal(np.asarray(caps2[0].image), a)


def test_real_caps_pick_the_truest_frame_not_frame_zero(tmp_path):
    import numpy as np
    from cap_mosaic.data.store import CapDataset, FrameRecord

    # frame 0 is a pale mis-capture; frame 1 matches the cap's true colour
    pale = _cap_crop_file(str(tmp_path / "cap_0000_f0.png"), color=(150, 120, 110))
    true = _cap_crop_file(str(tmp_path / "cap_0000_f1.png"), color=(200, 40, 40))
    dbp = tmp_path / "caps.db"
    with CapDataset(dbp) as db:
        db.add_cap((200, 40, 40), captured_at="t",
                   frames=[FrameRecord(frame_index=0, path=pale, rgb=(150, 120, 110)),
                           FrameRecord(frame_index=1, path=true, rgb=(200, 40, 40))],
                   diameter_mm=30.0, crop_span_mm=56.25)
    caps = cap_render._real_caps(str(dbp), 64, dbp.stat().st_mtime)
    a = np.asarray(caps[0].image)
    r, g, b, _ = a[32, 32]
    assert r > 170 and g < 90     # the crisp red frame won, not the pale one


def test_close_up_has_cap_texture_that_distance_blurs_away():
    plan = _plan()
    colors = list({tuple(c.rgb) for c in plan.cells if not c.is_hole})
    lib = cap_render.build_library(colors, size=48)
    mosaic = cap_render.render_mosaic_caps(plan, lib, px_per_cap=24)
    blurred = simulate_distance(mosaic, px_per_mm=24 / 32.0, distance_m=12.0)
    # up close the caps (rims/markings) create high-frequency detail; distance blurs it
    assert _hf_energy(mosaic) > _hf_energy(blurred)
