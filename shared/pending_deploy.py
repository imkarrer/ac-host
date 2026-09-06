"""Queue a prod tree for the 03:00 recycle. No SSH — files live on ac-box.

Buildkite (agent on the box) writes ``pending-deploy.json`` + ``pending-src/``.
``ac-host-nightly`` applies that tree into ``/var/lib/ac-host/src`` and then
runs ``recycle-static``. Players already get the Discord / in-game countdown.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PENDING_NAME = "pending-deploy.json"
APPLIED_NAME = "last-applied.json"
PENDING_SRC_NAME = "pending-src"

RSYNC_EXCLUDES = (
    ".git/",
    "__pycache__/",
    "_local_wipe_backup/",
    ".flox/cache/",
    ".flox/run/",
    ".flox/log/",
    "*.pyc",
    ".env",
)

SIDECAR_PATHS = ("sidecar/", "bot/", "compose/docker-compose.yml")


def state_dir(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    raw = os.environ.get("AC_STATE", "").strip()
    return Path(raw) if raw else Path("/var/lib/ac-host")


def src_dir() -> Path:
    raw = os.environ.get("AC_SRC", "").strip()
    return Path(raw) if raw else Path("/var/lib/ac-host/src")


def pending_path(state: Path | None = None) -> Path:
    return state_dir(state) / PENDING_NAME


def applied_path(state: Path | None = None) -> Path:
    return state_dir(state) / APPLIED_NAME


def pending_src_dir(state: Path | None = None) -> Path:
    return state_dir(state) / PENDING_SRC_NAME


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_pending(state: Path | None = None) -> dict[str, Any] | None:
    return load_json(pending_path(state))


def load_applied(state: Path | None = None) -> dict[str, Any] | None:
    return load_json(applied_path(state))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_pending(payload: dict[str, Any], state: Path | None = None) -> Path:
    path = pending_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_applied(payload: dict[str, Any], state: Path | None = None) -> Path:
    path = applied_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def clear_pending(state: Path | None = None) -> None:
    path = pending_path(state)
    if path.is_file():
        path.unlink()


def box_state_available(state: Path | None = None) -> bool:
    """True when this process can see the ac-box state directory."""
    return state_dir(state).is_dir()


def rebuild_sidecars_from_diff(changed_paths: list[str]) -> bool:
    for path in changed_paths:
        normalized = path.replace("\\", "/").lstrip("./")
        if any(normalized == item.rstrip("/") or normalized.startswith(item) for item in SIDECAR_PATHS):
            return True
    return False


def git_changed_paths(repo: Path, since: str, until: str = "HEAD") -> list[str]:
    if not since or not (repo / ".git").exists():
        return []
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", since, until],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def sync_tree(src: Path, dest: Path) -> None:
    """Replace dest with src, skipping caches and secrets."""
    if not src.is_dir():
        raise FileNotFoundError(f"sync source missing: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    rsync = shutil.which("rsync")
    if rsync:
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [rsync, "-a", "--delete"]
        for pattern in RSYNC_EXCLUDES:
            cmd.extend(["--exclude", pattern])
        cmd.extend([str(src) + "/", str(dest) + "/"])
        subprocess.run(cmd, check=True)
        return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            "_local_wipe_backup",
            "*.pyc",
            ".env",
        ),
        dirs_exist_ok=False,
    )
    flox_cache = dest / ".flox" / "cache"
    if flox_cache.exists():
        shutil.rmtree(flox_cache, ignore_errors=True)
