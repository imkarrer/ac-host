#!/usr/bin/env python3
"""Pack hosted practice cars and upload them to the GitHub `content` release."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from content_manifest import DOWNLOADABLE_CARS, RELEASE_TAG, write_content_json  # noqa: E402
from pack_content import pack_car  # noqa: E402


def ensure_release(owner: str, repo: str) -> None:
    slug = f"{owner}/{repo}"
    check = subprocess.run(
        ["gh", "release", "view", RELEASE_TAG, "--repo", slug],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                RELEASE_TAG,
                "--repo",
                slug,
                "--title",
                "Server content",
                "--notes",
                "Practice cars and tracks for ac-host lobbies.",
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=None)
    parser.add_argument("--repo", default=None)
    parser.add_argument(
        "--ac-root",
        type=Path,
        default=REPO.parent,
        help="Assetto Corsa install (parent of ac-host/)",
    )
    parser.add_argument("--out", type=Path, default=REPO / "dist")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument(
        "--car",
        action="append",
        default=[],
        help="Car folder to pack (default: all DOWNLOADABLE_CARS except the 124)",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Do not run check_car.py before zipping",
    )
    args = parser.parse_args()
    import settings
    from content_manifest import CAR, existing_car_version

    owner = args.owner or settings.github_owner()
    repo = args.repo or settings.github_pages_repo()
    if owner in ("", "OWNER") or not repo:
        raise SystemExit("set AC_GITHUB_OWNER / AC_GITHUB_REPO in .env or pass --owner/--repo")

    cars = list(args.car) or [item["id"] for item in DOWNLOADABLE_CARS if item["id"] != CAR]
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    zips = []
    for car in cars:
        zips.append(pack_car(args.ac_root, car, out, skip_check=args.skip_check))

    version = existing_car_version(REPO / "site" / "content.json") or "2.2"
    write_content_json(
        REPO / "site" / "content.json",
        owner,
        repo,
        car_version=version,
        content_root=args.ac_root,
    )
    write_content_json(
        out / "content.json",
        owner,
        repo,
        car_version=version,
        content_root=args.ac_root,
    )

    if args.no_upload:
        print("packed cars; skipped upload")
        return
    if not shutil.which("gh"):
        raise SystemExit("gh CLI not found; install GitHub CLI or pass --no-upload")

    slug = f"{owner}/{repo}"
    ensure_release(owner, repo)
    subprocess.run(
        ["gh", "release", "upload", RELEASE_TAG, *[str(path) for path in zips], "--repo", slug, "--clobber"],
        check=True,
    )
    print(f"uploaded {len(zips)} car zips to {slug} release {RELEASE_TAG}")


if __name__ == "__main__":
    main()
