"""Rig + perception sizing: turn the projector geometry and the human eye into
concrete numbers for a build.

Two independent things decide how a finished piece looks:

1. **Geometry (the projector).** A fixed-throw projector mounted height H above
   the table paints an image of width ``W = H / throw_ratio`` (16:9). With a cap
   pitch ``p`` that gives ``W / p`` caps across — and *caps-across is the real
   resolution of the piece*, exactly like pixels across an image.

2. **Perception (the eye).** Physical size does NOT change perceived detail —
   it only sets how far back you stand. A cap of pitch ``p`` seen at distance
   ``d`` subtends ``theta = p / d``. Below ~1 arcmin the eye cannot resolve a
   cap at all (pure blend); but a *picture* made of caps already "reads" once a
   cap subtends roughly 20-30 arcmin, because the brain integrates coarse tiles
   into an image (the same reason ~1 cm pixel-art reads from a few metres).

So the design loop is: pick caps-across for the detail you want, let the
projector throw fix the physical size, then stand at the distance where the
piece fills a comfortable field of view.
"""

from __future__ import annotations

import argparse

from ..core.sizing import (
    READS_ARCMIN,
    SMOOTH_ARCMIN,
    distance_for_arcmin,
    fov_distance,
    image_width_m,
)


def report(
    throw_ratio: float = 1.10,
    pitch_mm: float = 32.0,
    heights_m: tuple[float, ...] = (0.7, 0.9, 1.1, 1.3, 1.6),
    aspect: float = 16 / 9,
) -> str:
    p_m = pitch_mm / 1000.0
    lines = []
    lines.append(
        f"Projector throw {throw_ratio:.2f}:1, cap pitch {pitch_mm:.0f} mm, "
        f"16:9 frame.\n"
        f"(W = mount height / throw; depth = W*9/16; caps-across = W/pitch.)\n"
    )
    header = (
        f"{'height':>7} {'img W':>7} {'depth':>7} "
        f"{'across':>6} {'down':>5} {'~caps':>6} "
        f"{'view 40deg':>10} {'view 15deg':>10}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for h in heights_m:
        w = image_width_m(h, throw_ratio)
        depth = w / aspect
        across = int((w * 1000) // pitch_mm)
        down = int((depth * 1000) // pitch_mm)
        caps = across * down
        d_near = fov_distance(w, 40.0)
        d_far = fov_distance(w, 15.0)
        lines.append(
            f"{h:>6.2f}m {w*100:>6.0f}cm {depth*100:>6.0f}cm "
            f"{across:>6} {down:>5} {caps:>6} "
            f"{d_near:>9.1f}m {d_far:>9.1f}m"
        )

    d_reads = distance_for_arcmin(p_m, READS_ARCMIN)
    d_smooth = distance_for_arcmin(p_m, SMOOTH_ARCMIN)
    lines.append("")
    lines.append("Perception (independent of physical size):")
    lines.append(
        f"  - a {pitch_mm:.0f} mm cap subtends {READS_ARCMIN:.0f} arcmin at "
        f"{d_reads:.1f} m  -> picture 'reads' from here out"
    )
    lines.append(
        f"  - it subtends {SMOOTH_ARCMIN:.0f} arcmin at {d_smooth:.0f} m  "
        f"-> tiles look essentially smooth"
    )
    lines.append(
        "  - detail is set by caps-across, not size; a bigger piece is just "
        "viewed from further."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="cap-mosaic-sizing", description="projector + eye sizing for a build"
    )
    ap.add_argument("--throw", type=float, default=1.10, help="throw ratio (dist/width)")
    ap.add_argument("--pitch", type=float, default=32.0, help="cap pitch mm")
    ap.add_argument(
        "--heights",
        type=float,
        nargs="*",
        default=[0.7, 0.9, 1.1, 1.3, 1.6],
        help="projector mount heights (m) to tabulate",
    )
    args = ap.parse_args(argv)
    print(report(throw_ratio=args.throw, pitch_mm=args.pitch, heights_m=tuple(args.heights)))


if __name__ == "__main__":
    main()
