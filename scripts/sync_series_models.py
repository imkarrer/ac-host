#!/usr/bin/env python3
"""Push the full car folders a series needs onto ac-box's build content tree.

The server's own content tree is deliberately slim — the dedicated server needs
`data.acd` and skin folders, not models — but placing a race number is derived
from the car's `.kn5`, and packing the player-facing zip needs the whole folder.
So series cars get a second, complete copy under `services.ac-host.buildDir`.

This is a one-time cost per series car, repeated only when the car mod updates.

Usage:
  py -3 scripts/sync_series_models.py --series series-1
  py -3 scripts/sync_series_models.py --car ks_mazda_miata --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _path in (str(REPO / "shared"), str(REPO / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import series_lib  # noqa: E402

DEFAULT_HOST = "ac-box"
DEFAULT_BUILD = "/var/lib/ac-host/build"


def folder_size_mb(path: Path) -> float:
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return total / (1024 * 1024)


def cars_for_series(catalog: Path, series_ids: list[str]) -> list[str]:
    cars: list[str] = []
    for series_id in series_ids:
        car = str(series_lib.load_catalog(catalog, series_id).get("car") or "")
        if car and car not in cars:
            cars.append(car)
    return cars


def sync(car: str, *, content: Path, host: str, build: str, dry_run: bool) -> None:
    src = content / "cars" / car
    if not src.is_dir():
        raise SystemExit(f"no such car folder: {src}")
    if not list(src.glob("*.kn5")):
        raise SystemExit(f"{src} has no .kn5 — this looks like a slim copy, not the install")

    dest = f"{host}:{build}/content/cars/{car}/"
    size = folder_size_mb(src)
    print(f"{car}: {size:.0f} MB -> {dest}")
    if dry_run:
        return

    subprocess.run(["ssh", host, "mkdir", "-p", f"{build}/content/cars"], check=True)
    if shutil.which("rsync"):
        # Delta transfer, so a mod update only ships what changed.
        subprocess.run(["rsync", "-a", "--delete", "--info=progress2", f"{src}/", dest], check=True)
        return

    # Windows has no rsync. One tar stream is faster and safer than scp of
    # every file, and it does not blow the command line.
    print("rsync not found; streaming a tar over ssh")
    with subprocess.Popen(
        ["tar", "-cf", "-", "-C", str(src.parent), src.name],
        stdout=subprocess.PIPE,
    ) as archive:
        subprocess.run(
            ["ssh", host, f"tar -xf - -C {build}/content/cars"],
            stdin=archive.stdout,
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", action="append", default=[], help="Series id; repeatable")
    parser.add_argument("--car", action="append", default=[], help="Car folder; repeatable")
    parser.add_argument("--catalog", type=Path, default=REPO / "catalog")
    parser.add_argument("--content", type=Path, default=REPO.parent / "content")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--build", default=DEFAULT_BUILD)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cars = list(args.car)
    if args.series:
        for car in cars_for_series(args.catalog, args.series):
            if car not in cars:
                cars.append(car)
    if not cars:
        raise SystemExit("nothing to sync; pass --series or --car")

    for car in cars:
        sync(
            car,
            content=args.content,
            host=args.host,
            build=args.build,
            dry_run=args.dry_run,
        )
    print(f"{'would sync' if args.dry_run else 'synced'} {len(cars)} car folder(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
