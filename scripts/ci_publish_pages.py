#!/usr/bin/env python3
"""Render the player page and publish the allowed files to GitHub Pages.

Never touches leaderboard.json -- it is absent from ALLOWED, so live lap rows
are not this script's to overwrite.

Two ways to publish, checked in order:

  AC_PAGES_CHECKOUT  a git clone of the Pages repo on the box. Works, but the
                     clone is long-lived mutable state that nothing reconciles,
                     which is how /var/lib/ac-host/src drifted from git.
  GITHUB_STATUS_TOKEN + GITHUB_STATUS_REPO
                     the Contents API, same credential and repo push_status.py
                     already uses. No checkout, so nothing to drift.

Either way AC_PAGES_PUSH must be truthy. Render-only otherwise.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

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


API_HEADERS = {
    "User-Agent": "ac-host-publish-pages",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def push_enabled() -> bool:
    return os.environ.get("AC_PAGES_PUSH", "").strip() in ("1", "true", "yes")


def blob_sha(data: bytes) -> str:
    """Git's object id for this content, so an unchanged file can be skipped.

    Publishing runs on every green build; without this each one would commit
    all eight files whether or not anything changed.
    """
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def api_publish(out: Path, repo: str, token: str, branch: str, message: str) -> int:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise SystemExit(f"invalid GITHUB_STATUS_REPO: {repo!r}")
    auth = {**API_HEADERS, "Authorization": f"Bearer {token}"}
    pushed = 0
    for rel in ALLOWED:
        src = out / rel
        if not src.is_file():
            continue
        data = src.read_bytes()
        url = f"https://api.github.com/repos/{owner}/{name}/contents/{quote(rel, safe='/')}"
        existing = None
        try:
            req = Request(f"{url}?ref={quote(branch)}", headers=auth)
            with urlopen(req, timeout=30) as resp:
                existing = json.loads(resp.read().decode("utf-8")).get("sha")
        except HTTPError as exc:
            if exc.code != 404:
                raise
        if existing and existing == blob_sha(data):
            print(f"unchanged {rel}")
            continue
        payload = {
            "message": message,
            "content": base64.b64encode(data).decode("ascii"),
            "branch": branch,
        }
        if existing:
            payload["sha"] = existing
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**auth, "Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(req, timeout=30) as resp:
            resp.read()
        print(f"published {rel}")
        pushed += 1
    return pushed


def main() -> int:
    out = REPO / "dist" / "site"
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "render_site.py"), "--out", str(out)],
        check=True,
    )

    raw = os.environ.get("AC_PAGES_CHECKOUT", "").strip()
    if not raw:
        token = os.environ.get("GITHUB_STATUS_TOKEN", "").strip()
        repo = os.environ.get("GITHUB_STATUS_REPO", "").strip()
        if not (token and repo):
            print("no AC_PAGES_CHECKOUT and no GITHUB_STATUS_TOKEN/REPO; rendered only")
            return 0
        if not push_enabled():
            print("AC_PAGES_PUSH unset; rendered only")
            return 0
        sha = (os.environ.get("BUILDKITE_COMMIT") or "")[:12]
        branch = os.environ.get("GITHUB_STATUS_BRANCH", "main").strip() or "main"
        n = api_publish(out, repo, token, branch, f"Publish site from ac-host {sha}".strip())
        print("pages already up to date" if n == 0 else f"published {n} file(s)")
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

    if not push_enabled():
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
