"""Card-driven build: read a cap from the card and decide accept/reject.

This module holds the device-independent decision logic (testable headless). The
live capture + projector loop is added in ``main`` (real-rig only).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.matcher import Match, Matcher
from ..core.plan import PlannedCell
from ..vision.card_reader import CapReading, CardCapReader


@dataclass
class FrameResult:
    reading: CapReading | None  # None = no card visible
    match: Match | None

    @property
    def state(self) -> str:
        if self.reading is None:
            return "idle"
        if self.match is not None and self.match.accepted:
            return "accept"
        return "reject"

    @property
    def cell(self) -> PlannedCell | None:
        return self.match.cell if self.match is not None else None


def process_frame(frame_rgb, reader: CardCapReader, matcher: Matcher) -> FrameResult:
    """Read a cap from the card in `frame_rgb` and match it to the plan."""
    reading = reader.read(frame_rgb)
    if reading is None:
        return FrameResult(None, None)
    return FrameResult(reading, matcher.match(reading.rgb))
