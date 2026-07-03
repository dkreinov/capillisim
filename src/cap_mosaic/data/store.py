"""CapDataset: the SQLite-backed cap inventory + training dataset.

Why SQLite and not the original ``labels.csv``: the capture loop produces more
than a flat row per cap — several colour-corrected crops per cap, per-frame
colour and a quality (spread) signal, and eventually brand/logo embeddings and
inventory queries. A normalised single-file DB holds all of that, stays
queryable, evolves through migrations, needs no server, and ports to a phone.

Design rules:
- **Crops stay as files.** We store each crop's *path* and a content hash, never
  the image bytes — the DB stays small and git/backup-friendly.
- **No colour bucketing at capture time.** We store true measured RGB/Lab; which
  caps map to which painting colour is decided per-painting at plan time.
- **Schema version** lives in ``PRAGMA user_version``; `_MIGRATIONS` upgrades an
  older file in place. Opening a file newer than the code is a hard error.

Tables: ``cap`` (one physical cap) 1—* ``frame`` (its crops), ``cap`` 1—*
``embedding`` (future features), plus a ``meta`` key/value table.
"""

from __future__ import annotations

import sqlite3
from array import array
from dataclasses import dataclass, field
from pathlib import Path

from ..core.palette import RGB, Lab, ciede2000, rgb_to_lab

# ── records ──────────────────────────────────────────────────────────────────


@dataclass
class FrameRecord:
    """One colour-corrected crop saved for a cap."""

    frame_index: int
    path: str
    rgb: RGB | None = None
    lab: Lab | None = None
    glare_frac: float | None = None
    sha256: str | None = None


# A cap is "ambiguous" when its field colour can't be trusted as a single tile
# colour: either the field/marking split is near 50/50 (no clear field), or the
# per-frame reads disagree (the field cluster flipped between frames). Such caps
# should be re-read, excluded, or stored as two colours — not matched on one RGB.
AMBIGUOUS_MARKING = 0.40  # marking fraction at/above which field vs logo is unclear
AMBIGUOUS_COLOR_STD = 10.0  # per-frame CIEDE2000 spread signalling an unstable read


def size_class_of(diameter_mm: float | None) -> str | None:
    """'standard-26' | 'large-38' | 'other', or None if unmeasured.

    Sizes are of USED caps: crimping flares a nominal 26 mm crown's skirt to
    ~29–31 mm across the teeth, so the standard class is generous. Nominal 26 vs
    29 mm crowns are indistinguishable once flared — one class.
    """
    if diameter_mm is None:
        return None
    if diameter_mm < 33.0:
        return "standard-26"
    if diameter_mm >= 35.0:
        return "large-38"
    return "other"


@dataclass
class CapRecord:
    """One physical cap and its measured colour."""

    id: int
    captured_at: str
    rgb: RGB
    lab: Lab
    color_std: float | None = None
    marking_frac: float | None = None
    mosaic_rgb: RGB | None = None  # at-distance colour (linear mean); None until backfilled
    diameter_mm: float | None = None  # physical size measured off the card (v4)
    crop_span_mm: float | None = None  # crop window width; legacy rows = 37.8 implied
    n_frames: int = 0
    source: str = "unknown"
    brand: str | None = None
    notes: str | None = None
    frames: list[FrameRecord] = field(default_factory=list)

    @property
    def size_class(self) -> str | None:
        return size_class_of(self.diameter_mm)

    @property
    def is_ambiguous(self) -> bool:
        """True if the stored field colour is not a trustworthy single tile colour."""
        return (self.marking_frac or 0.0) >= AMBIGUOUS_MARKING or (
            self.color_std or 0.0
        ) > AMBIGUOUS_COLOR_STD


# ── schema / migrations ──────────────────────────────────────────────────────

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS cap (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT    NOT NULL,
    r INTEGER NOT NULL, g INTEGER NOT NULL, b INTEGER NOT NULL,
    lab_l REAL NOT NULL, lab_a REAL NOT NULL, lab_b REAL NOT NULL,
    color_std REAL,
    n_frames  INTEGER NOT NULL DEFAULT 0,
    source    TEXT    NOT NULL DEFAULT 'unknown',
    brand     TEXT,
    notes     TEXT
);

CREATE TABLE IF NOT EXISTS frame (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cap_id      INTEGER NOT NULL REFERENCES cap(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL,
    path        TEXT    NOT NULL,
    r INTEGER, g INTEGER, b INTEGER,
    lab_l REAL, lab_a REAL, lab_b REAL,
    glare_frac REAL,
    sha256     TEXT
);
CREATE INDEX IF NOT EXISTS idx_frame_cap ON frame(cap_id);

CREATE TABLE IF NOT EXISTS embedding (
    cap_id     INTEGER NOT NULL REFERENCES cap(id) ON DELETE CASCADE,
    model      TEXT    NOT NULL,
    dim        INTEGER NOT NULL,
    vec        BLOB    NOT NULL,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (cap_id, model)
);
"""


def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_V1)


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    # Busy-ness of the cap: fraction of pixels in the marking (logo/text) cluster
    # vs the field. NULL on legacy rows captured before field/marking splitting.
    conn.execute("ALTER TABLE cap ADD COLUMN marking_frac REAL")


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    # Mosaic colour: the cap's at-distance contribution (linear-light area mean
    # of the whole face, logo included — see app.cap_color). Distinct from the
    # field colour (r,g,b), which recognises a cap in hand. NULL until backfilled.
    for col in ("mosaic_r", "mosaic_g", "mosaic_b"):
        conn.execute(f"ALTER TABLE cap ADD COLUMN {col} INTEGER")


def _migrate_to_v4(conn: sqlite3.Connection) -> None:
    # Physical size: diameter measured off the card's mm-true homography
    # (standard crown ~26mm, champagne 29mm, large 38mm), and the crop window
    # width used for this cap's frames so mm-per-pixel stays derivable. NULL on
    # legacy rows (crop_span_mm effectively 37.8 for them).
    conn.execute("ALTER TABLE cap ADD COLUMN diameter_mm REAL")
    conn.execute("ALTER TABLE cap ADD COLUMN crop_span_mm REAL")


# index i (0-based) upgrades a DB from user_version i to i+1.
_MIGRATIONS = [_migrate_to_v1, _migrate_to_v2, _migrate_to_v3, _migrate_to_v4]
SCHEMA_VERSION = len(_MIGRATIONS)


# ── store ────────────────────────────────────────────────────────────────────


class CapDataset:
    """Open (creating if needed) a cap dataset at `path`.

    Use as a context manager, or remember to ``close()``.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"{self.path} is schema v{version}, but this code only knows "
                f"v{SCHEMA_VERSION}. Upgrade cap_mosaic."
            )
        for v in range(version, SCHEMA_VERSION):
            _MIGRATIONS[v](self.conn)
            self.conn.execute(f"PRAGMA user_version = {v + 1}")
        self.conn.commit()

    # ── writing ──────────────────────────────────────────────────────────────

    def add_cap(
        self,
        rgb: RGB,
        frames: list[FrameRecord] | None = None,
        *,
        captured_at: str,
        source: str = "card_capture",
        color_std: float | None = None,
        marking_frac: float | None = None,
        mosaic_rgb: RGB | None = None,
        diameter_mm: float | None = None,
        crop_span_mm: float | None = None,
        brand: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Insert one cap (and its frames); returns the new cap id.

        ``lab`` is derived from ``rgb``. If ``color_std`` is not given but frames
        carry colours, it is computed as the largest CIEDE2000 between the cap's
        colour and any single frame — a built-in glare/outlier quality signal.
        """
        frames = frames or []
        lab = rgb_to_lab(rgb)
        if color_std is None:
            spreads = [
                ciede2000(lab, f.lab if f.lab else rgb_to_lab(f.rgb))
                for f in frames
                if f.rgb is not None or f.lab is not None
            ]
            color_std = max(spreads) if spreads else None

        m = mosaic_rgb or (None, None, None)
        cur = self.conn.execute(
            "INSERT INTO cap (captured_at, r, g, b, lab_l, lab_a, lab_b, "
            "color_std, marking_frac, mosaic_r, mosaic_g, mosaic_b, "
            "diameter_mm, crop_span_mm, n_frames, source, brand, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (captured_at, rgb[0], rgb[1], rgb[2], lab[0], lab[1], lab[2],
             color_std, marking_frac, m[0], m[1], m[2],
             diameter_mm, crop_span_mm, len(frames), source, brand, notes),
        )
        cap_id = int(cur.lastrowid)
        for fr in frames:
            flab = fr.lab if fr.lab else (rgb_to_lab(fr.rgb) if fr.rgb else None)
            self.conn.execute(
                "INSERT INTO frame (cap_id, frame_index, path, r, g, b, "
                "lab_l, lab_a, lab_b, glare_frac, sha256) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cap_id, fr.frame_index, fr.path,
                 fr.rgb[0] if fr.rgb else None,
                 fr.rgb[1] if fr.rgb else None,
                 fr.rgb[2] if fr.rgb else None,
                 flab[0] if flab else None,
                 flab[1] if flab else None,
                 flab[2] if flab else None,
                 fr.glare_frac, fr.sha256),
            )
        self.conn.commit()
        return cap_id

    def add_embedding(
        self, cap_id: int, model: str, vec, *, created_at: str
    ) -> None:
        """Store a feature/brand embedding for a cap (float32 BLOB)."""
        buf = array("f", list(vec))
        self.conn.execute(
            "INSERT OR REPLACE INTO embedding (cap_id, model, dim, vec, created_at) "
            "VALUES (?,?,?,?,?)",
            (cap_id, model, len(buf), buf.tobytes(), created_at),
        )
        self.conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    def delete_cap(self, cap_id: int, remove_crops: bool = True) -> bool:
        """Remove a cap (and its frames/embeddings); returns False if not found.

        Also deletes the cap's crop PNGs from disk when ``remove_crops`` is set,
        so an unwanted/misread cap leaves nothing behind.
        """
        paths = [
            r["path"]
            for r in self.conn.execute(
                "SELECT path FROM frame WHERE cap_id = ?", (cap_id,)
            )
        ]
        cur = self.conn.execute("DELETE FROM cap WHERE id = ?", (cap_id,))
        self.conn.commit()
        if cur.rowcount == 0:
            return False
        if remove_crops:
            for p in paths:
                try:
                    Path(p).unlink()
                except OSError:
                    pass
        return True

    def set_mosaic(self, cap_id: int, rgb: RGB) -> None:
        """Set/replace a cap's mosaic (at-distance) colour — used by the backfill."""
        self.conn.execute(
            "UPDATE cap SET mosaic_r = ?, mosaic_g = ?, mosaic_b = ? WHERE id = ?",
            (rgb[0], rgb[1], rgb[2], cap_id),
        )
        self.conn.commit()

    def set_field(self, cap_id: int, rgb: RGB) -> None:
        """Set/replace a cap's field colour (Lab re-derived) — used by capture repair."""
        lab = rgb_to_lab(rgb)
        self.conn.execute(
            "UPDATE cap SET r = ?, g = ?, b = ?, lab_l = ?, lab_a = ?, lab_b = ? "
            "WHERE id = ?",
            (rgb[0], rgb[1], rgb[2], lab[0], lab[1], lab[2], cap_id),
        )
        self.conn.commit()

    def set_diameter(self, cap_id: int, mm: float) -> None:
        """Set/replace a cap's measured diameter — used by the size backfill."""
        self.conn.execute("UPDATE cap SET diameter_mm = ? WHERE id = ?", (mm, cap_id))
        self.conn.commit()

    def set_notes(self, cap_id: int, text: str) -> None:
        self.conn.execute("UPDATE cap SET notes = ? WHERE id = ?", (text, cap_id))
        self.conn.commit()

    def get_embeddings(self, model: str) -> list[tuple[int, list[float]]]:
        """All (cap_id, vector) pairs stored for `model` (float32 round-trip)."""
        out: list[tuple[int, list[float]]] = []
        for row in self.conn.execute(
            "SELECT cap_id, dim, vec FROM embedding WHERE model = ? ORDER BY cap_id",
            (model,),
        ):
            buf = array("f")
            buf.frombytes(row["vec"])
            out.append((row["cap_id"], list(buf)))
        return out

    def last_cap_id(self) -> int | None:
        """Id of the most recently added cap, or None if the dataset is empty."""
        row = self.conn.execute("SELECT id FROM cap ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"] if row else None

    # ── reading ──────────────────────────────────────────────────────────────

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM cap").fetchone()[0])

    def colors(self) -> list[RGB]:
        """Every cap's measured RGB — the inventory for palette clustering."""
        return [
            (row["r"], row["g"], row["b"])
            for row in self.conn.execute("SELECT r, g, b FROM cap ORDER BY id")
        ]

    def caps(self, *, with_frames: bool = False) -> list[CapRecord]:
        rows = self.conn.execute("SELECT * FROM cap ORDER BY id").fetchall()
        caps = [self._row_to_cap(r) for r in rows]
        if with_frames:
            by_id = {c.id: c for c in caps}
            for fr in self.conn.execute("SELECT * FROM frame ORDER BY cap_id, frame_index"):
                cap = by_id.get(fr["cap_id"])
                if cap is not None:
                    cap.frames.append(self._row_to_frame(fr))
        return caps

    @staticmethod
    def _row_to_cap(r: sqlite3.Row) -> CapRecord:
        mosaic = (
            (r["mosaic_r"], r["mosaic_g"], r["mosaic_b"])
            if r["mosaic_r"] is not None
            else None
        )
        return CapRecord(
            id=r["id"],
            captured_at=r["captured_at"],
            rgb=(r["r"], r["g"], r["b"]),
            lab=(r["lab_l"], r["lab_a"], r["lab_b"]),
            color_std=r["color_std"],
            marking_frac=r["marking_frac"],
            mosaic_rgb=mosaic,
            diameter_mm=r["diameter_mm"],
            crop_span_mm=r["crop_span_mm"],
            n_frames=r["n_frames"],
            source=r["source"],
            brand=r["brand"],
            notes=r["notes"],
        )

    @staticmethod
    def _row_to_frame(r: sqlite3.Row) -> FrameRecord:
        rgb = (r["r"], r["g"], r["b"]) if r["r"] is not None else None
        lab = (r["lab_l"], r["lab_a"], r["lab_b"]) if r["lab_l"] is not None else None
        return FrameRecord(
            frame_index=r["frame_index"],
            path=r["path"],
            rgb=rgb,
            lab=lab,
            glare_frac=r["glare_frac"],
            sha256=r["sha256"],
        )

    # ── lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "CapDataset":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def import_labels_csv(
    db: CapDataset, csv_path: str | Path, crops_dir: str | Path | None = None,
    captured_at: str = "1970-01-01T00:00:00",
) -> int:
    """Import a legacy ``labels.csv`` (index,r,g,b[,nearest],n_frames) into `db`.

    Links the per-cap crop PNGs (``cap_<index>_f<k>.png``) as frames if
    ``crops_dir`` is given. Returns the number of caps imported.
    """
    import csv

    crops_dir = Path(crops_dir) if crops_dir else None
    n = 0
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            rgb = (int(row["r"]), int(row["g"]), int(row["b"]))
            frames: list[FrameRecord] = []
            if crops_dir:
                for p in sorted(crops_dir.glob(f"cap_{int(row['index']):04d}_f*.png")):
                    k = int(p.stem.split("_f")[-1])
                    frames.append(FrameRecord(frame_index=k, path=str(p)))
            db.add_cap(rgb, frames, captured_at=captured_at, source="labels.csv")
            n += 1
    return n
