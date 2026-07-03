"""The interactive build loop (Milestone 3 / the POC).

Ties the pieces together: capture a cap frame -> recognize its color -> match to
the best empty cell (or reject) -> project the highlight -> confirm placement ->
persist -> repeat. All hardware touchpoints (camera, projector display, the
user's confirmation) are injected as callables, so the whole loop runs and tests
headless with synthetic inputs, and the same code drives the real rig by passing
real grabber/display/confirm functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PIL import Image

from ..core.matcher import InventoryCap, Match, Matcher
from ..core.plan import GridPlan
from ..procam.calibrate import Calibration
from ..procam.render import render_projection
from ..vision.cap_reader import read_dominant_color


def matcher_inventory_from_db(path) -> tuple[InventoryCap, ...]:
    """Load (field, mosaic) pairs from caps.db for identify-then-place matching.

    Legacy rows without a mosaic colour use the field for both (flat-cap
    behaviour); run ``app.backfill_mosaic`` to fill them properly.
    """
    from ..data.store import CapDataset

    with CapDataset(path) as db:
        return tuple(
            InventoryCap(field=c.rgb, mosaic=c.mosaic_rgb or c.rgb) for c in db.caps()
        )

CapSource = Callable[[], Optional[Image.Image]]  # returns a frame, or None to stop
Display = Callable[[Image.Image], None]  # show a projector frame
Confirm = Callable[[Match], bool]  # True = cap placed, False = skipped
OnSave = Callable[[GridPlan], None]


@dataclass
class BuildStats:
    placed: int = 0
    rejected: int = 0
    skipped: int = 0

    @property
    def seen(self) -> int:
        return self.placed + self.rejected + self.skipped


class BuildSession:
    """Holds the live state and turns frames into matches + projector frames."""

    def __init__(
        self,
        plan: GridPlan,
        cal: Calibration,
        reject_threshold: float | None = None,
        inventory: tuple[InventoryCap, ...] | None = None,
    ):
        self.plan = plan
        self.cal = cal
        kwargs = {"inventory": inventory} if inventory else {}
        self.matcher = (
            Matcher(plan, reject_threshold, **kwargs)
            if reject_threshold is not None
            else Matcher(plan, **kwargs)
        )

    def recognize_and_match(self, frame: Image.Image) -> Match:
        # identify-then-place: the live read is a FIELD colour (recognition key);
        # with an inventory the matcher places by the identified cap's MOSAIC.
        return self.matcher.match_cap(read_dominant_color(frame))

    def projection(self, highlight=None) -> Image.Image:
        return render_projection(self.plan, self.cal, highlight=highlight)

    def accept(self, match: Match) -> None:
        if match.cell is not None:
            self.matcher.place(match.cell)


def run_loop(
    session: BuildSession,
    cap_source: CapSource,
    display: Display,
    confirm: Confirm,
    on_save: OnSave | None = None,
) -> BuildStats:
    """Drive the build until `cap_source` returns None."""
    stats = BuildStats()
    while True:
        frame = cap_source()
        if frame is None:
            break
        match = session.recognize_and_match(frame)
        if not match.accepted:
            stats.rejected += 1
            display(session.projection())  # no glow => "set this cap aside"
            continue
        display(session.projection(highlight=match.cell))
        if confirm(match):
            session.accept(match)
            stats.placed += 1
            if on_save is not None:
                on_save(session.plan)
        else:
            stats.skipped += 1
    return stats
