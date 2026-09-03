#!/usr/bin/env python3
"""Compatibility wrapper. Prefer: python scripts/pack_content.py --car abarth_124_2016"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_content import pack_car


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ac-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--car", default="abarth_124_2016")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out_dir = args.out.parent if args.out else Path(__file__).resolve().parents[1] / "dist"
    dest = pack_car(args.ac_root, args.car, out_dir)
    if args.out and dest != args.out:
        dest.replace(args.out)


if __name__ == "__main__":
    main()
