#!/usr/bin/env python3
"""Copy server-side track/car files from a local Assetto Corsa install."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def load_track(catalog: Path, track_id: str) -> dict:
    path = catalog / "tracks" / f"{track_id}.json"
    if not path.is_file():
        raise SystemExit(f"unknown track {track_id!r}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def copy_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def copy_car(ac_root: Path, dest_root: Path, car: str) -> None:
    src = ac_root / "content" / "cars" / car
    if not src.is_dir():
        raise SystemExit(f"missing car {car}: {src}")
    dest = dest_root / "cars" / car
    dest.mkdir(parents=True, exist_ok=True)
    data_acd = src / "data.acd"
    data_dir = src / "data"
    if data_acd.is_file():
        shutil.copy2(data_acd, dest / "data.acd")
        if (dest / "data.acd").read_bytes() != data_acd.read_bytes():
            raise SystemExit(f"checksum mismatch after copy: {car} data.acd")
    elif data_dir.is_dir():
        copy_tree(data_dir, dest / "data")
    else:
        raise SystemExit(f"{car} has neither data.acd nor data/")
    skins = src / "skins"
    if skins.is_dir():
        copy_tree(skins, dest / "skins")
    print(f"car  {car} -> {dest}")


def copy_track(ac_root: Path, dest_root: Path, folder: str) -> None:
    slim = ac_root / "server" / "content" / "tracks" / folder
    full = ac_root / "content" / "tracks" / folder
    src = slim if slim.is_dir() else full
    if not src.is_dir():
        raise SystemExit(f"missing track {folder}: tried {slim} and {full}")
    dest = dest_root / "tracks" / folder
    copy_tree(src, dest)
    print(f"track {folder} -> {dest}  (from {src})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ac-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Assetto Corsa install (parent of ac-host/)",
    )
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--track", required=True, help="Catalog id, e.g. magione or blackhawk")
    parser.add_argument("--dest", type=Path, default=None)
    parser.add_argument("--cars", nargs="*", default=None, help="Override catalog car list")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    catalog = args.catalog or (repo / "catalog")
    dest = args.dest or (repo / "content")
    track = load_track(catalog, args.track)
    cars = args.cars or list(track["cars"])

    copy_track(args.ac_root, dest, track["folder"])
    for car in cars:
        copy_car(args.ac_root, dest, car)
    print(f"content ready at {dest}")


if __name__ == "__main__":
    main()
