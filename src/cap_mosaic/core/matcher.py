"""Match a cap you're holding to the best empty cell, or reject it.

Given the color read off a cap, find the unfilled cell whose target color is the
closest perceptual match. If even the closest is too far, the cap doesn't help
this piece and is rejected ("set aside"). This is the greedy strategy suited to
an open-ended, partial cap supply; scarcity-aware assignment (don't spend a rare
color on a cell a common cap could fill) is a later enhancement.

Pure core: no camera, no projector.
"""

from __future__ import annotations

from dataclasses import dataclass

from .palette import RGB, CapColor, distance
from .plan import GridPlan, PlannedCell

# CIEDE2000 above which a cap is considered not worth placing. ~25 keeps obvious
# matches and rejects clearly-wrong colors; tune against real caps later.
DEFAULT_REJECT_THRESHOLD = 25.0


@dataclass
class Match:
    cell: PlannedCell | None
    delta_e: float
    accepted: bool


class Matcher:
    def __init__(self, plan: GridPlan, reject_threshold: float = DEFAULT_REJECT_THRESHOLD):
        self.plan = plan
        self.reject_threshold = reject_threshold

    def match(self, rgb: RGB) -> Match:
        """Best empty cell for a cap of color `rgb`, or a rejection."""
        empties = [c for c in self.plan.cells if not c.filled]
        if not empties:
            return Match(cell=None, delta_e=float("inf"), accepted=False)
        # closest target color; tie-break top-left so the build fills predictably
        best = min(
            empties,
            key=lambda c: (
                distance(rgb, CapColor(c.color_name, tuple(c.rgb))),
                c.row,
                c.col,
            ),
        )
        d = distance(rgb, CapColor(best.color_name, tuple(best.rgb)))
        return Match(cell=best, delta_e=d, accepted=d <= self.reject_threshold)

    def place(self, cell: PlannedCell) -> None:
        cell.filled = True
