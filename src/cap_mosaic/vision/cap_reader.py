"""Read the dominant color of a cap from a camera frame.

For the POC the cap is held up filling the frame (or its centre), so we don't yet
need full circle detection — we take a robust central sample and mask out
specular glare, since metallic caps throw bright highlights that would otherwise
skew the color. Pure numpy/Pillow so it tests headless; the live phone-stream
grabber (OpenCV) is a thin, lazily-imported shell function.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..core.palette import RGB

GLARE_LEVEL = 240  # pixels brighter than this in all channels are treated as glare


def read_dominant_color(
    image: Image.Image,
    center_fraction: float = 1.0,
    glare_level: int = GLARE_LEVEL,
) -> RGB:
    """Median color of the (optionally central) cap region, ignoring glare."""
    arr = np.asarray(image.convert("RGB"))
    h, w = arr.shape[:2]
    if center_fraction < 1.0:
        ch, cw = int(h * center_fraction), int(w * center_fraction)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        arr = arr[y0 : y0 + ch, x0 : x0 + cw]
    pixels = arr.reshape(-1, 3)
    not_glare = ~np.all(pixels > glare_level, axis=1)
    sample = pixels[not_glare] if not_glare.any() else pixels
    return tuple(int(v) for v in np.median(sample, axis=0))


def phone_frame_grabber(url: str):  # pragma: no cover - needs a phone + network
    """Return a callable that grabs one frame from a phone MJPEG stream.

    Used on the real rig; imports OpenCV lazily so the rest of the package has no
    hard dependency on it.
    """
    import cv2  # noqa: PLC0415

    cap = cv2.VideoCapture(url)

    def grab() -> Image.Image | None:
        ok, frame = cap.read()
        if not ok:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    return grab
