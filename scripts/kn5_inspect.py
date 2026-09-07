#!/usr/bin/env python3
"""Inspect a car KN5: textures, materials, meshes, and UV bounding boxes.

Usage:
  py -3 scripts/kn5_inspect.py --car ks_mazda_miata
  py -3 scripts/kn5_inspect.py --car ks_mazda_miata --match door
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import kn5  # noqa: E402


def main_kn5(content: Path, car: str) -> Path:
    car_dir = content / "cars" / car
    candidates = sorted(
        (p for p in car_dir.glob("*.kn5") if "lod" not in p.name.lower() and p.name != "collider.kn5"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"no kn5 in {car_dir}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, default=REPO.parent / "content")
    parser.add_argument("--car", required=True)
    parser.add_argument("--match", default="", help="Only show meshes whose name contains this")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    path = main_kn5(args.content, args.car)
    model = kn5.read_kn5(path)
    print(f"kn5: {path.name}  version={model.version}  trailing_bytes={model.trailing_bytes}")
    print(f"textures: {len(model.textures)}")
    for name in sorted(model.textures):
        print(f"  {name}  ({len(model.textures[name])} bytes)")
    print(f"materials: {len(model.materials)}")
    print(f"meshes: {len(model.meshes)}")

    needle = args.match.lower()
    shown = 0
    for mesh in model.meshes:
        if needle and needle not in mesh.name.lower():
            continue
        mat = model.material_for(mesh)
        bbox = mesh.uv_bbox()
        bbox_s = (
            f"u[{bbox[0]:.3f},{bbox[2]:.3f}] v[{bbox[1]:.3f},{bbox[3]:.3f}]" if bbox else "no-uv"
        )
        print(
            f"  {mesh.name:32s} tris={mesh.triangle_count:6d} "
            f"mat={mat.name if mat else '?':24s} tex={model.texture_for(mesh):24s} {bbox_s}"
        )
        shown += 1
        if shown >= args.limit:
            print("  …")
            break


if __name__ == "__main__":
    main()
