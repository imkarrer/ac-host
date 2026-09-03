#!/usr/bin/env python3
"""Pack the patched 124 Spider and upload to a GitHub Release."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from pack_content import pack_car  # noqa: E402

CAR = "abarth_124_2016"
ZIP_NAME = f"{CAR}.zip"
RELEASE_TAG = "content"


def release_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{RELEASE_TAG}/{ZIP_NAME}"


def pages_url(owner: str, repo: str) -> str:
    return f"https://{owner}.github.io/{repo}/"


def write_content_json(path: Path, owner: str, repo: str, version: str = "1.3") -> None:
    payload = {
        "cars": {
            CAR: {
                "url": release_url(owner, repo),
                "version": version,
            }
        }
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")


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
                "Patched Abarth 124 Spider for ac-host practice lobbies.",
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=None, help="GitHub username or org (default: AC_GITHUB_OWNER)")
    parser.add_argument("--repo", default=None, help="Pages repo name (default: AC_GITHUB_REPO)")
    parser.add_argument(
        "--ac-root",
        type=Path,
        default=REPO.parent,
        help="Assetto Corsa install (parent of ac-host/)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "dist",
        help="Where to write the zip before upload",
    )
    parser.add_argument("--skip-check", action="store_true")
    parser.add_argument("--no-upload", action="store_true", help="Pack only; do not call gh")
    args = parser.parse_args()
    sys.path.insert(0, str(REPO / "scripts"))
    import settings

    owner = args.owner or settings.github_owner()
    repo = args.repo or settings.github_pages_repo()
    if owner in ("", "OWNER") or not repo:
        raise SystemExit("set AC_GITHUB_OWNER / AC_GITHUB_REPO in .env or pass --owner/--repo")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    zip_path = pack_car(args.ac_root, CAR, out, skip_check=args.skip_check)

    site_content = REPO / "site" / "content.json"
    write_content_json(site_content, owner, repo)

    dist_content = out / "content.json"
    write_content_json(dist_content, owner, repo)

    if args.no_upload:
        print(f"packed {zip_path}; skipped upload")
        return

    if not shutil.which("gh"):
        raise SystemExit("gh CLI not found; install GitHub CLI or pass --no-upload")

    slug = f"{owner}/{repo}"
    ensure_release(owner, repo)
    subprocess.run(
        ["gh", "release", "upload", RELEASE_TAG, str(zip_path), "--repo", slug, "--clobber"],
        check=True,
    )
    print(f"uploaded {ZIP_NAME} to {release_url(owner, repo)}")
    print(f"Pages URL: {pages_url(owner, repo)}")


if __name__ == "__main__":
    main()
