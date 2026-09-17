#!/usr/bin/env python3
"""03:00 deploy: apply the folded pending tree, then recycle practice once.

The Discord countdown queues this job (DOWNTIME=1). Last green
``queue-prod`` wins. ``/downtime-drill`` must not call this.
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
    wanted = bool(pending.get("rebuild_sidecars"))
    # Recorded in the applied stamp, and read back by ci_queue_prod.py: a
    # recreate that was wanted but skipped (image missing, .env missing) must
    # not be forgotten just because the NEXT diff, taken against this sha,
    # touches no sidecar path -- that is old code and old image running
    # indefinitely with every record saying "applied".
    recreated = _recreate_sidecars(dest, state) if wanted else False
    pending_deploy.write_applied(
        {
            "sha": sha,
            "applied_at": pending_deploy.utcnow(),
            "rebuild_sidecars": wanted,
            "sidecars_recreated": recreated or not wanted,
            "queued_at": pending.get("queued_at", ""),
            "source": "buildkite-downtime",
        },
        state,
    )
    pending_deploy.clear_pending(state)
    print(f"applied {sha}")
    return sha


def _recreate_sidecars(src: Path, state: Path) -> bool:
    """Restart the bot and sidecars onto the tree just synced and the current image.

    Returns whether the recreate was issued; False is a skip the caller records.

    Nothing is built here. The image (``ac-host-env:latest``) was built by CI's
    ``image`` step with ``flox containerize`` and loaded into this daemon before
    the tree was even queued; the code is bind-mounted from ``src``. So the
    03:00 window depends on neither PyPI nor Docker Hub, which ``up --build``
    used to reach for -- and ``--force-recreate`` is what makes a container pick
    up the new bind-mounted code, since ``up -d`` alone sees an unchanged
    definition and leaves the old process running.
    """
    compose = src / "compose" / "docker-compose.yml"
    envf = state / ".env"
    if not compose.is_file() or not envf.is_file():
        print("sidecar recreate skipped: compose or .env missing")
        return False
    if not pending_deploy.docker_image_exists(pending_deploy.PYTHON_IMAGE):
        print(
            f"sidecar recreate skipped: {pending_deploy.PYTHON_IMAGE} is not in the Docker daemon. "
            "CI's image step (scripts/ci_containerize.sh) loads it on a green main build; "
            "the running containers are left as they are."
        )
        return False
    base = ["docker", "compose", "-f", str(compose), "--env-file", str(envf)]
    print("recreating sidecars")
    subprocess.run(base + ["up", "-d", "--force-recreate", "auth", "plugin", "details"], check=False)
    subprocess.run(base + ["--profile", "bot", "up", "-d", "--force-recreate", "bot"], check=False)
    return True


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
