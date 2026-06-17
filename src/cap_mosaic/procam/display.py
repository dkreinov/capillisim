"""Fullscreen projector output (real-rig only).

The projector is a second monitor; this puts a borderless fullscreen window on
it and pushes PIL frames to it. OpenCV is imported lazily so the rest of the
package keeps testing headless with no hard GUI dependency.

Finding the projector's X offset on Windows: it is the virtual-desktop x
coordinate of the extended display, usually the width of your primary screen
(e.g. 1920 if the laptop is 1920 wide and the projector is to its right). Pass
it as ``monitor_x``; the window is moved there and then made fullscreen.
"""

from __future__ import annotations

from PIL import Image

WINDOW = "capillisim"


class Projector:
    """A borderless fullscreen window living on the projector's display."""

    def __init__(self, monitor_x: int = 0, monitor_y: int = 0, window: str = WINDOW):
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        self._cv2 = cv2
        self._np = np
        self.window = window
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        # Move onto the projector first, then flip to fullscreen on that monitor.
        cv2.moveWindow(window, monitor_x, monitor_y)
        cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    @property
    def cv2(self):
        return self._cv2

    def show(self, img: Image.Image, hold_ms: int = 1) -> int:
        """Display a PIL frame; returns the key pressed during `hold_ms` (or -1)."""
        frame = self._cv2.cvtColor(
            self._np.asarray(img.convert("RGB")), self._cv2.COLOR_RGB2BGR
        )
        self._cv2.imshow(self.window, frame)
        return self._cv2.waitKey(max(1, hold_ms)) & 0xFF

    def wait_key(self, ms: int = 0) -> int:
        return self._cv2.waitKey(ms) & 0xFF

    def close(self) -> None:
        try:
            self._cv2.destroyWindow(self.window)
        except Exception:  # pragma: no cover - window already gone
            pass

    def __enter__(self) -> "Projector":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
