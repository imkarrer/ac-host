#!/usr/bin/env python3
"""Validate an already-built numbered skin without rebuilding it.

Checks that the skin overrides the car's real body diffuse, that the badge sits
inside the door UV island, and that it shows up in an offline side render.

Usage:
  py -3 scripts/validate_race_number.py --car ks_mazda_miata --skin race_787 \
      --number 787 --base-skin 05_sunburst_yellow
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
    parser.add_argument("--skin", required=True)
    parser.add_argument("--number", required=True)
    parser.add_argument("--base-skin", default=None, help="Skin the numbered one was built from")
    parser.add_argument("--render-width", type=int, default=900)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    report = skin_livery.validate_numbered_skin(
        content=args.content,
        catalog=args.catalog,
        car=args.car,
        skin=args.skin,
        number=args.number,
        base_skin=args.base_skin,
        render_width=args.render_width,
        write_report=not args.no_report,
    )
    print(report.text())
    if report.report_dir:
        print(f"\nproof: {report.report_dir}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
