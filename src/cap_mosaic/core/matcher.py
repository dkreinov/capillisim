"""Match a cap you're holding to the best empty cell, or reject it.

Given the color read off a cap, find the unfilled cell whose target color is the
closest perceptual match. If even the closest is too far, the cap doesn't help
this piece and is rejected ("set aside"). This is the greedy strategy suited to
an open-ended, partial cap supply; scarcity-aware assignment (don't spend a rare
color on a cell a common cap could fill) is a later enhancement.

Identify-then-place: a cap has two colours — the *field* (dominant body colour,
what a live camera read produces) and the *mosaic* (its at-distance contribution,
what plan slots are matched against). With an ``inventory``, ``match_cap`` first
identifies which known cap the field read is (the key), then places by that
cap's mosaic colour (the value). Without one, it behaves like plain ``match``.

Pure core: no camera, no projector.
"""

from __future__ import annotations

from dataclasses import dataclass

from .palette import RGB, CapColor, distance
from .plan import GridPlan, PlannedCell

# CIEDE2000 above which a cap is considered not worth placing. ~25 keeps obvious
# matches and rejects clearly-wrong colors; tune against real caps later.
DEFAULT_REJECT_THRESHOLD = 25.0
# CIEDE2000 within which a live field read counts as one of the known inventory
# caps; farther reads are treated as an unknown cap (use the raw read as-is).
DEFAULT_IDENTIFY_THRESHOLD = 10.0


@dataclass(frozen=True)
class InventoryCap:
    """A known cap: field colour = recognition key, mosaic = placement colour."""

    field: RGB
    mosaic: RGB


@dataclass
class Match:
    cell: PlannedCell | None
    delta_e: float
    accepted: bool


class Matcher:
    def __init__(
        self,
        plan: GridPlan,
        reject_threshold: float = DEFAULT_REJECT_THRESHOLD,
        inventory: tuple[InventoryCap, ...] | None = None,
        identify_threshold: float = DEFAULT_IDENTIFY_THRESHOLD,
    ):
        self.plan = plan
        self.reject_threshold = reject_threshold
        self.inventory = inventory or ()
        self.identify_threshold = identify_threshold

    def resolve(self, field_rgb: RGB) -> RGB:
        """The colour to place by: the identified cap's mosaic, or the raw read.

        A busy cap's field colour (e.g. a muddy beige from a white+green+red cap)
        is a stable *key*, not what the cap looks like from distance — placing by
        it puts the cap in the wrong slot. Identify the cap first, then use its
        mosaic colour. Unknown caps (no close inventory field) keep the raw read.
        """
        if not self.inventory:
            return field_rgb
        best = min(self.inventory, key=lambda c: distance(field_rgb, CapColor("", c.field)))
        d = distance(field_rgb, CapColor("", best.field))
        return best.mosaic if d <= self.identify_threshold else field_rgb

    def match_cap(self, field_rgb: RGB) -> Match:
        """Identify the cap from its live field read, then match by its mosaic."""
        return self.match(self.resolve(field_rgb))

    def match(self, rgb: RGB) -> Match:
        """Best empty cell for a cap of color `rgb`, or a rejection."""
        empties = [c for c in self.plan.cells if not c.filled and not c.is_hole]
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
