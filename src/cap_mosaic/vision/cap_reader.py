"""Read the dominant color of a cap from a camera frame.

For the POC the cap is held up filling the frame (or its centre), so we don't yet
need full circle detection — we take a robust central sample and mask out
specular glare, since metallic caps throw bright highlights that would otherwise
skew the color. Pure numpy/Pillow so it tests headless; the live phone-stream
grabber (OpenCV) is a thin, lazily-imported shell function.
"""

from __future__ import annotations

import base64
import io
import urllib.request
from urllib.parse import unquote, urlsplit, urlunsplit

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


def grab_snapshot(url: str, timeout: float = 5.0) -> Image.Image:
    """Fetch a single JPEG frame from a phone's snapshot endpoint over HTTP.

    Works with just the standard library + Pillow (no OpenCV), which makes it the
    lowest-friction way to confirm the phone <-> PC link on the same network. The
    URL is the IP-webcam app's still-image endpoint, e.g.
    ``http://192.168.1.42:8080/shot.jpg``. If the app has a login set, embed the
    credentials in the URL (``http://user:pass@host:8080/shot.jpg``); a username
    containing ``@`` should be percent-encoded as ``%40``. The credentials are
    pulled out and sent as an HTTP Basic ``Authorization`` header, since
    ``urlopen`` does not handle inline userinfo itself.
    """
    parts = urlsplit(url)
    headers = {}
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, netloc = netloc.rsplit("@", 1)
        user, _, pwd = userinfo.partition(":")
        token = base64.b64encode(
            f"{unquote(user)}:{unquote(pwd)}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {token}"
    clean_url = urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )
    req = urllib.request.Request(clean_url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = resp.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


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
