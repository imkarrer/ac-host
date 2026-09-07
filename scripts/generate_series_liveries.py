#!/usr/bin/env python3
"""Generate the whole grid's numbered skins for one series round.

Runs after quali closes: every driver on the grid gets a skin folder whose body
texture carries their registered number, and the round records which skin the
race entry list should hand each driver.

The pack is all-or-nothing. A skin that fails its offline proof would still
change the car's checksum, so a partial pack breaks joins for everyone rather
than just the one driver: skins are built into a staging tree and only copied
into content once every driver passes.

Usage:
  python scripts/generate_series_liveries.py --series series-1
  python scripts/generate_series_liveries.py --series series-1 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "shared"
for _path in (str(SHARED), str(REPO / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import render_cfg  # noqa: E402
import series_lib  # noqa: E402
import skin_livery  # noqa: E402

NUMBER_MIN = 1
NUMBER_MAX = 999


@dataclass
class Entry:
    """One driver's inputs to the pack."""

    steam_id: str
    name: str
    number: str
    base_skin: str
    output_skin: str = ""
    checks: int = 0
    texture: str = ""
    sha256: str = ""
    seconds: float = 0.0
    failures: list[str] = field(default_factory=list)


def series_slug(series_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", series_id.lower())


def output_skin_name(series_id: str, number: str) -> str:
    """Deterministic folder name, so re-running the pack is idempotent.

    Deliberately has no round in it. Numbers are frozen at signup close and
    qualifying only sorts the grid, so a driver wears the same skin all season —
    putting the round in the name would rebuild identical skins every week and
    make every driver re-download the car zip for nothing.
    """
    return skin_livery.validate_output_name(f"{series_slug(series_id)}_{number}")


def roster(
    *,
    state: Path,
    catalog: Path,
    series_id: str,
    default_skin: str,
) -> tuple[str, list[Entry]]:
    """Every signed-up driver for the season, since the pack is season-scoped."""
    spec = series_lib.load_catalog(catalog, series_id, state)
    car = str(spec.get("car") or "")
    if not car:
        raise SystemExit(f"series {series_id} has no car")

    signups = series_lib.load_signups(state, series_id)
    fallback = default_skin or render_cfg.PREFERRED_SKIN.get(car, "")
    entries: list[Entry] = []
    for driver in signups.get("drivers") or []:
        sid = str(driver.get("steam_id") or "")
        if not sid:
            continue
        entries.append(
            Entry(
                steam_id=sid,
                name=str(driver.get("name") or sid),
                number=str(driver.get("number") or "").strip(),
                base_skin=str(driver.get("skin") or "") or fallback,
            )
        )
    return car, entries


def check_roster(entries: list[Entry], content: Path, car: str) -> None:
    """Fail before doing any work if the roster cannot produce a clean pack."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for entry in entries:
        if not entry.number:
            problems.append(f"{entry.name} ({entry.steam_id}) has no number")
            continue
        if not entry.number.isdigit() or not NUMBER_MIN <= int(entry.number) <= NUMBER_MAX:
            problems.append(f"{entry.name}: number {entry.number!r} outside {NUMBER_MIN}-{NUMBER_MAX}")
            continue
        # Two drivers sharing a number would collide on the skin folder and ship
        # one driver the other's livery.
        if entry.number in seen:
            problems.append(f"number {entry.number} claimed by both {seen[entry.number]} and {entry.name}")
        seen[entry.number] = entry.name
        if not entry.base_skin:
            problems.append(f"{entry.name}: no colour and no default skin for {car}")
        elif not skin_livery.skin_dir(content, car, entry.base_skin).is_dir():
            problems.append(f"{entry.name}: base skin {entry.base_skin!r} not in content")
    if problems:
        raise SystemExit("roster is not ready:\n  " + "\n  ".join(problems))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# A chunk pays the car's kn5-parse and paint-bake cost once, so splitting a
# colour across workers only helps when there are enough drivers to amortize it.
MIN_CHUNK = 3


def plan_chunks(entries: list[Entry], jobs: int) -> list[tuple[str, list[Entry]]]:
    """Group drivers by colour, splitting big groups so ``jobs`` workers stay busy."""
    by_colour: dict[str, list[Entry]] = {}
    for entry in entries:
        by_colour.setdefault(entry.base_skin, []).append(entry)
    chunks = [(colour, drivers) for colour, drivers in by_colour.items()]
    while len(chunks) < jobs:
        chunks.sort(key=lambda item: -len(item[1]))
        colour, drivers = chunks[0]
        if len(drivers) < 2 * MIN_CHUNK:
            break
        half = len(drivers) // 2
        chunks[0] = (colour, drivers[:half])
        chunks.append((colour, drivers[half:]))
    return chunks


def _build_chunk(task: dict) -> list[dict]:
    """Build one colour's skins. Runs in a worker process, so args stay picklable."""
    content = Path(task["content"])
    catalog = Path(task["catalog"])
    car = task["car"]
    plan = skin_livery.prepare_car(
        content=content,
        catalog=catalog,
        car=car,
        base_skin=task["base_skin"],
        render_width=task["render_width"],
    )
    results = []
    for item in task["drivers"]:
        started = time.perf_counter()
        _dst, report = skin_livery.generate_numbered_skin(
            content=content,
            catalog=catalog,
            car=car,
            base_skin=task["base_skin"],
            number=item["number"],
            output_skin=item["output_skin"],
            out_content=Path(task["staging"]),
            pixel_format=task["pixel_format"],
            max_texture_size=task["max_texture_size"],
            render_width=task["render_width"],
            write_report=task["keep_reports"],
            force=True,  # keep the artefacts so a failure can be inspected
            plan=plan,
        )
        results.append(
            {
                "steam_id": item["steam_id"],
                "checks": len(report.checks),
                "texture": plan.target.texture,
                "failures": [c.name for c in report.checks if not c.ok],
                "seconds": time.perf_counter() - started,
            }
        )
    return results


def build_pack(
    *,
    content: Path,
    catalog: Path,
    car: str,
    series_id: str,
    entries: list[Entry],
    staging: Path,
    pixel_format: str,
    max_texture_size: int,
    render_width: int,
    keep_reports: bool,
    jobs: int = 1,
) -> list[Entry]:
    """Build every skin into ``staging``; returns entries that failed the proof."""
    for entry in entries:
        entry.output_skin = output_skin_name(series_id, entry.number)

    chunks = plan_chunks(entries, jobs)
    tasks = [
        {
            "content": str(content),
            "catalog": str(catalog),
            "car": car,
            "staging": str(staging),
            "base_skin": colour,
            "pixel_format": pixel_format,
            "max_texture_size": max_texture_size,
            "render_width": render_width,
            "keep_reports": keep_reports,
            "drivers": [
                {
                    "steam_id": e.steam_id,
                    "number": e.number,
                    "output_skin": e.output_skin,
                }
                for e in drivers
            ],
        }
        for colour, drivers in chunks
    ]
    print(f"building {len(tasks)} colour chunks on {min(jobs, len(tasks))} worker(s)", flush=True)

    by_steam = {entry.steam_id: entry for entry in entries}
    done = 0

    def absorb(results: list[dict]) -> None:
        nonlocal done
        for result in results:
            entry = by_steam[result["steam_id"]]
            entry.checks = result["checks"]
            entry.texture = result["texture"]
            entry.failures = result["failures"]
            entry.seconds = result["seconds"]
            done += 1
            status = "ok" if not entry.failures else "FAIL " + ", ".join(entry.failures)
            print(
                f"  [{done}/{len(entries)}] #{entry.number:>3} {entry.name} "
                f"({entry.base_skin}) {entry.seconds:.1f}s {status}",
                flush=True,
            )

    if jobs <= 1 or len(tasks) == 1:
        for task in tasks:
            absorb(_build_chunk(task))
    else:
        with ProcessPoolExecutor(max_workers=min(jobs, len(tasks))) as pool:
            for results in pool.map(_build_chunk, tasks):
                absorb(results)

    return [entry for entry in entries if entry.failures]


def commit_pack(
    *,
    staging: Path,
    content: Path,
    car: str,
    entries: list[Entry],
    also: list[Path] | None = None,
) -> None:
    """Copy proved skins out of staging, into content and any other tree.

    ``also`` exists for the slim tree the game servers and the CM details API
    read: it has no car models, so it cannot be the build tree, but it still
    needs the skin folders that `entry_list.ini` names.
    """
    targets = [content, *(also or [])]
    for entry in entries:
        src = skin_livery.skin_dir(staging, car, entry.output_skin)
        for index, root in enumerate(targets):
            dst = skin_livery.skin_dir(root, car, entry.output_skin)
            if dst.exists():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
            if index == 0:
                entry.sha256 = sha256_file(dst / entry.texture)


def pack_dir(state: Path, series_id: str) -> Path:
    return series_lib.series_state_dir(state, series_id) / "race_pack"


def write_manifest(
    *,
    state: Path,
    series_id: str,
    car: str,
    entries: list[Entry],
    pixel_format: str,
    max_texture_size: int,
) -> Path:
    out = pack_dir(state, series_id)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "series_id": series_id,
        "car": car,
        "generated_at": series_lib.utcnow(),
        "pixel_format": pixel_format,
        "max_texture_size": max_texture_size,
        "drivers": [
            {
                "steam_id": entry.steam_id,
                "name": entry.name,
                "number": entry.number,
                "base_skin": entry.base_skin,
                "race_skin": entry.output_skin,
                "texture": entry.texture,
                "sha256": entry.sha256,
                "checks_passed": entry.checks,
            }
            for entry in entries
        ],
    }
    path = out / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def write_race_skins(*, state: Path, series_id: str, entries: list[Entry]) -> int:
    """Record race_skin on the signup row — the pack predates any round's grid."""
    signups = series_lib.load_signups(state, series_id)
    by_steam = {entry.steam_id: entry for entry in entries}
    updated = 0
    for driver in signups.get("drivers") or []:
        entry = by_steam.get(str(driver.get("steam_id") or ""))
        if entry is None:
            continue
        driver["race_skin"] = entry.output_skin
        updated += 1
    series_lib.save_signups(state, series_id, signups)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", required=True)
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(os.environ.get("AC_STATE") or REPO / "STATE"),
    )
    parser.add_argument("--catalog", type=Path, default=REPO / "catalog")
    parser.add_argument("--content", type=Path, default=REPO.parent / "content")
    parser.add_argument(
        "--out-content",
        type=Path,
        default=None,
        help="Write the pack here instead of into --content (staging for a zip build)",
    )
    parser.add_argument(
        "--serve-content",
        type=Path,
        default=None,
        help="Also copy proved skins into the slim tree the game servers read",
    )
    parser.add_argument(
        "--default-skin",
        default="",
        help="Colour for drivers who did not pick one (default: the car's PREFERRED_SKIN)",
    )
    parser.add_argument("--pixel-format", default=skin_livery.DEFAULT_PIXEL_FORMAT)
    parser.add_argument(
        "--max-texture-size",
        type=int,
        default=0,
        help="Downscale each body texture's long edge; 0 keeps full size",
    )
    parser.add_argument("--render-width", type=int, default=900)
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Worker processes; 0 picks one per colour chunk, up to the core count",
    )
    parser.add_argument(
        "--keep-reports",
        action="store_true",
        help="Keep the per-skin proof renders (bigger pack, useful when debugging)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the roster and print the plan without building anything",
    )
    args = parser.parse_args()

    try:
        car, entries = roster(
            state=args.state,
            catalog=args.catalog,
            series_id=args.series,
            default_skin=args.default_skin,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not entries:
        print(f"error: no signed-up drivers for {args.series}", file=sys.stderr)
        return 2

    check_roster(entries, args.content, car)

    target_content = args.out_content or args.content
    jobs = args.jobs if args.jobs > 0 else max(1, min(os.cpu_count() or 1, len(entries)))
    print(f"{args.series}: {len(entries)} drivers on {car}")
    colours = sorted({e.base_skin for e in entries})
    print(f"colours: {len(colours)} ({', '.join(colours)}) = {len(colours)} kn5/paint passes")
    if args.dry_run:
        for entry in entries:
            print(
                f"  #{entry.number:>3} {entry.name} {entry.base_skin} "
                f"-> {output_skin_name(args.series, entry.number)}"
            )
        return 0

    started = time.perf_counter()
    staging_root = Path(tempfile.mkdtemp(prefix=f"racepack_{series_slug(args.series)}_"))
    try:
        failed = build_pack(
            content=args.content,
            catalog=args.catalog,
            car=car,
            series_id=args.series,
            entries=entries,
            staging=staging_root,
            pixel_format=args.pixel_format,
            max_texture_size=args.max_texture_size,
            render_width=args.render_width,
            keep_reports=args.keep_reports,
            jobs=jobs,
        )
        elapsed = time.perf_counter() - started
        if failed:
            print(
                f"\n{len(failed)} of {len(entries)} skins failed the offline proof; "
                "nothing was published.",
                file=sys.stderr,
            )
            for entry in failed:
                print(f"  #{entry.number} {entry.name}: {', '.join(entry.failures)}", file=sys.stderr)
            print(f"staging kept for inspection: {staging_root}", file=sys.stderr)
            staging_root = None  # skip cleanup
            return 1

        commit_pack(
            staging=staging_root,
            content=target_content,
            car=car,
            entries=entries,
            also=[args.serve_content] if args.serve_content else None,
        )
    finally:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)

    manifest = write_manifest(
        state=args.state,
        series_id=args.series,
        car=car,
        entries=entries,
        pixel_format=args.pixel_format,
        max_texture_size=args.max_texture_size,
    )
    tagged = write_race_skins(state=args.state, series_id=args.series, entries=entries)

    per_driver = elapsed / len(entries)
    print(
        f"\n{len(entries)} skins built and proved in {elapsed:.1f}s "
        f"({per_driver:.1f}s/driver), {entries[0].checks} checks each"
    )
    print(f"content: {skin_livery.skin_dir(target_content, car, entries[0].output_skin).parent}")
    if args.serve_content:
        print(f"served:  {skin_livery.skin_dir(args.serve_content, car, entries[0].output_skin).parent}")
    print(f"manifest: {manifest}")
    print(f"signups tagged with race_skin: {tagged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
