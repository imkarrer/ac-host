#!/usr/bin/env python3
"""03:00 deploy: apply the folded pending tree, then recycle practice once.

Last green ``queue-prod`` wins (pending-src is one directory). This job is the
only recycle — do not unblock every paused Apply-now step.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "shared") not in sys.path:
    sys.path.insert(0, str(REPO / "shared"))

import pending_deploy  # noqa: E402

CHICAGO = ZoneInfo("America/Chicago")
STAMP_NAME = "last-downtime.json"


def chicago_date() -> str:
    return datetime.now(CHICAGO).date().isoformat()


def stamp_path(state: Path) -> Path:
    return state / STAMP_NAME


def load_stamp(state: Path) -> dict | None:
    return pending_deploy.load_json(stamp_path(state))


def write_stamp(state: Path, sha: str) -> None:
    stamp_path(state).write_text(
        json.dumps({"date": chicago_date(), "sha": sha, "at": pending_deploy.utcnow()}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def apply_pending(state: Path) -> str:
    pending = pending_deploy.load_pending(state)
    if pending is None:
        print("no pending deploy")
        return ""
    sha = str(pending.get("sha") or "")
    applied = pending_deploy.load_applied(state) or {}
    if sha and sha == str(applied.get("sha") or ""):
        print(f"already applied {sha}")
        pending_deploy.clear_pending(state)
        return sha
    staged = pending_deploy.pending_src_dir(state)
    if not staged.is_dir():
        raise SystemExit(f"pending-src missing at {staged}")
    dest = pending_deploy.src_dir()
    print(f"apply {sha or '(unknown)'} -> {dest}")
    pending_deploy.sync_tree(staged, dest)
    if pending.get("rebuild_sidecars"):
        _rebuild_sidecars(dest, state)
    pending_deploy.write_applied(
        {
            "sha": sha,
            "applied_at": pending_deploy.utcnow(),
            "rebuild_sidecars": bool(pending.get("rebuild_sidecars")),
            "queued_at": pending.get("queued_at", ""),
            "source": "buildkite-downtime",
        },
        state,
    )
    pending_deploy.clear_pending(state)
    print(f"applied {sha}")
    return sha


def _rebuild_sidecars(src: Path, state: Path) -> None:
    compose = src / "compose" / "docker-compose.yml"
    envf = state / ".env"
    if not compose.is_file() or not envf.is_file():
        print("sidecar rebuild skipped: compose or .env missing")
        return
    base = ["docker", "compose", "-f", str(compose), "--env-file", str(envf)]
    print("rebuilding sidecars")
    subprocess.run(base + ["up", "-d", "--build", "auth", "plugin", "details"], check=False)
    subprocess.run(base + ["--profile", "bot", "up", "-d", "--build", "bot"], check=False)


def recycle_static(src: Path) -> None:
    probe = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if probe.returncode != 0:
        raise SystemExit(
            "docker info failed — mount /var/run/docker.sock on the agent "
            f"(stderr: {(probe.stderr or probe.stdout or '').strip()[:300]})"
        )
    acctl = src / "scripts" / "acctl.py"
    if not acctl.is_file():
        raise SystemExit(f"acctl missing at {acctl}")
    subprocess.run([sys.executable, str(acctl), "--env", "prod", "recycle-static"], check=True)


def main() -> int:
    state = pending_deploy.state_dir()
    if not pending_deploy.box_state_available(state):
        print(f"skip downtime: {state} is not a directory")
        return 0
    sha = apply_pending(state)
    stamp = load_stamp(state) or {}
    if stamp.get("date") == chicago_date():
        print(f"recycle already ran {stamp.get('date')} (sha={stamp.get('sha')}); skip")
        return 0
    src = pending_deploy.src_dir()
    print(f"recycle-static from {src}")
    recycle_static(src)
    write_stamp(state, sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
