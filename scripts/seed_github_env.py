#!/usr/bin/env python3
"""Merge GitHub Pages / status-push settings into AC_STATE/.env.

Reads GITHUB_STATUS_TOKEN from stdin (pipe `gh auth token`).

  gh auth token | sudo AC_STATE=/var/lib/ac-host python3 seed_github_env.py --env prod
  gh auth token | sudo AC_STATE=/var/lib/ac-host-dev python3 seed_github_env.py --env dev
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings  # noqa: E402


def profile_updates(env_name: str) -> dict[str, str]:
    owner = settings.github_owner()
    repo = settings.github_pages_repo()
    if env_name == "dev":
        return {
            "AC_GITHUB_OWNER": owner,
            "AC_GITHUB_REPO": repo,
            "AC_PAGES_URL": settings.pages_url(dev=True),
            "GITHUB_STATUS_REPO": settings.github_status_repo(),
            "GITHUB_STATUS_BRANCH": os.environ.get("GITHUB_STATUS_BRANCH", "main").strip()
            or "main",
            "GITHUB_STATUS_PATH": "dev/leaderboard.json",
        }
    return {
        "AC_GITHUB_OWNER": owner,
        "AC_GITHUB_REPO": repo,
        "AC_PAGES_URL": settings.pages_url(),
        "GITHUB_STATUS_REPO": settings.github_status_repo(),
        "GITHUB_STATUS_BRANCH": os.environ.get("GITHUB_STATUS_BRANCH", "main").strip() or "main",
        "GITHUB_STATUS_PATH": "leaderboard.json",
    }


PROFILES_STATE = {
    "prod": "/var/lib/ac-host",
    "dev": "/var/lib/ac-host-dev",
}
REMOVE = {"AC_CONTENT_URL"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env",
        choices=sorted(PROFILES_STATE),
        default=os.environ.get("AC_ENV", "prod"),
    )
    args = parser.parse_args()

    token = sys.stdin.read().strip()
    if not token:
        raise SystemExit("empty token on stdin; pipe: gh auth token | ...")

    # Prefer values already in the target .env / process env.
    state = Path(os.environ.get("AC_STATE", PROFILES_STATE[args.env]))
    path = state / ".env"
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")

    updates = profile_updates(args.env)
    updates["GITHUB_STATUS_TOKEN"] = token

    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in REMOVE:
            continue
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"updated {path} ({args.env}: GITHUB_STATUS_PATH={updates['GITHUB_STATUS_PATH']})")


if __name__ == "__main__":
    main()
