#!/usr/bin/env python3
"""Generate a numbered skin for any AC car and prove it offline.

Placement comes from the car KN5 (body material diffuse + door UV island), and
the skin is discarded unless the side-view render shows the badge on the car.

Usage:
  py -3 scripts/generate_race_number.py --car ks_mazda_miata \
      --skin 05_sunburst_yellow --number 787 --output race_787
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import skin_livery  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, default=REPO.parent / "content")
    parser.add_argument("--catalog", type=Path, default=REPO / "catalog")
    parser.add_argument("--car", required=True)
    parser.add_argument("--skin", required=True, help="Base skin folder to copy")
    parser.add_argument("--number", required=True)
    parser.add_argument("--output", required=True, help="New skin folder name")
    parser.add_argument("--out-content", type=Path, default=None)
    parser.add_argument("--pixel-format", default=skin_livery.DEFAULT_PIXEL_FORMAT)
    parser.add_argument(
        "--max-texture-size",
        type=int,
        default=0,
        help="Downscale the body texture to this many pixels on the long edge (0 = keep)",
    )
    parser.add_argument("--render-width", type=int, default=900)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Keep the skin even if validation fails (debugging only)",
    )
    args = parser.parse_args()

    try:
        dst, report = skin_livery.generate_numbered_skin(
            content=args.content,
            catalog=args.catalog,
            car=args.car,
            base_skin=args.skin,
            number=args.number,
            output_skin=args.output,
            out_content=args.out_content,
            pixel_format=args.pixel_format,
            max_texture_size=args.max_texture_size,
            render_width=args.render_width,
            force=args.force,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report.text())
    print(f"\nskin: {dst}")
    if report.report_dir:
        print(f"proof: {report.report_dir}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
