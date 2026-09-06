#!/usr/bin/env python3
"""Render the player page and copy allowed files into the Pages checkout.

Never overwrites live lap rows in leaderboard.json. Needs AC_PAGES_CHECKOUT
on the box (a git clone of imkarrer/ac-practice). Render-only if unset.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

ALLOWED = (
    "index.html",
    "app.js",
    "style.css",
    "series.html",
    "series.js",
    "dev/index.html",
    "content.json",
    "dev/content.json",
)


def main() -> int:
    out = REPO / "dist" / "site"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "render_site.py"), "--out", str(out)],
        check=True,
    )

    raw = os.environ.get("AC_PAGES_CHECKOUT", "").strip()
    if not raw:
        print("AC_PAGES_CHECKOUT unset; rendered only")
        return 0
    pages = Path(raw)
    if not pages.is_dir():
        raise SystemExit(f"AC_PAGES_CHECKOUT is not a directory: {pages}")

    copied = 0
    for rel in ALLOWED:
        src = out / rel
        if not src.is_file():
            continue
        dest = pages / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
        print(f"copied {rel}")
    if copied == 0:
        raise SystemExit("render produced no allowed files")

    if os.environ.get("AC_PAGES_PUSH", "").strip() not in ("1", "true", "yes"):
        print("AC_PAGES_PUSH unset; left files in the checkout uncommitted")
        return 0

    subprocess.run(["git", "-C", str(pages), "add", "--", *ALLOWED], check=False)
    status = subprocess.run(
        ["git", "-C", str(pages), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        print("pages checkout already up to date")
        return 0
    sha = (os.environ.get("BUILDKITE_COMMIT") or "")[:12]
    subprocess.run(
        [
            "git",
            "-C",
            str(pages),
            "-c",
            "user.name=ac-host-ci",
            "-c",
            "user.email=ac-host-ci@localhost",
            "commit",
            "-m",
            f"Publish site from ac-host {sha}".strip(),
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(pages), "push"], check=True)
    print("pushed pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
