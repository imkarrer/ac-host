"""Queue a prod tree for the 03:00 recycle. No SSH — files live on ac-box.

Buildkite (agent on the box) writes ``pending-deploy.json`` + ``pending-src/``.
The bot's 03:00 countdown queues ``DOWNTIME=1``, which applies that tree
into ``/var/lib/ac-host/src`` and then runs ``recycle-static``.
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

# Machine-local state that lives in the deployed tree but is deliberately NOT in
# git, so it can never appear in pending-src. Without these excludes, the
# `rsync --delete` below removes them and the next nixos-rebuild silently
# degrades the box:
#
#   hardware-configuration.nix  -> configuration.nix falls back to the .example
#                                  stub, which says of itself "will not boot a
#                                  real machine". The switch succeeds, writes
#                                  boot entries from the stub, and the box does
#                                  not come back from its next reboot.
#   ssh-keys.local.nix          -> sshKeys evaluates to [ ], removing every
#                                  authorized key for root and nixosuser.
#
# Anything else that is gitignored *and* lives under the deployed tree belongs
# in this list too.
#
#   dist/*.zip, dist/content.json  -> car-content downloads and the manifest
#                                      the player page and CM read to fetch
#                                      them. Gitignored (built once, some of
#                                      it hand-placed third-party
#                                      redistributables), and not rebuilt by
#                                      any deploy step -- an rsync --delete
#                                      here breaks download links with no
#                                      error until a player's client 404s.
#
#   .env.*                         -> compose/.env.buildkite holds the live
#                                     BUILDKITE_AGENT_TOKEN, MINIO_ROOT_PASSWORD
#                                     and S3 cache keys. The plain ".env" entry
#                                     below does NOT cover it: rsync matches that
#                                     pattern as an exact basename, and
#                                     ".env.buildkite" is not ".env". Deleting it
#                                     leaves the CI agent and the binary cache
#                                     without credentials.
#
#   _extract/                      -> 452 MB of intermediate car-content
#                                     tarballs, referenced by
#                                     scripts/pack_content.py so not scratch.
#                                     gr86 and civic have finished dist/ zips,
#                                     but e30 and na-elise do not -- roughly
#                                     87 MB of packaging work whose only copy
#                                     is here. Caught by dry-running the very
#                                     first sync before letting it run.
PRESERVE_LOCAL = (
    "hosts/*/hardware-configuration.nix",
    "hosts/*/ssh-keys.local.nix",
    "dist/*.zip",
    "dist/content.json",
    ".env.*",
    "_extract/",
)

RSYNC_EXCLUDES = (
    ".git/",
    "__pycache__/",
    "_local_wipe_backup/",
    ".flox/cache/",
    ".flox/run/",
    ".flox/log/",
    "*.pyc",
    ".env",
) + PRESERVE_LOCAL

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


WIPE_BACKUP_NAME = "_local_wipe_backup"

# ci_queue_prod.py also calls sync_tree (checkout -> pending-src), so one full
# deploy cycle produces TWO snapshots rather than one. Observed on the first live
# run: 20260908T000728Z from the queue and 20260908T001316Z from the apply. Keep
# 10 so that is five cycles of history instead of two and a half.
WIPE_BACKUP_KEEP = 10


def wipe_backup_root(dest: Path) -> Path:
    """Where pre-sync snapshots live: a sibling of the synced tree.

    Derived from `dest` rather than from state_dir(), so it follows whatever tree
    is actually being synced and needs no plumbing through callers. In production
    dest is <state>/src, which puts snapshots at <state>/_local_wipe_backup.

    Deliberately a sibling, never inside dest: rsync would otherwise recurse into
    its own backups. `_local_wipe_backup/` has been in RSYNC_EXCLUDES since long
    before this function existed, implying a backup mechanism that was never
    actually written -- sync_tree had no backup or rollback of any kind.
    """
    return dest.parent / WIPE_BACKUP_NAME


def prune_wipe_backups(dest: Path, keep: int = WIPE_BACKUP_KEEP) -> list[Path]:
    """Keep the newest `keep` snapshots. Returns what was removed."""
    root = wipe_backup_root(dest)
    if not root.is_dir():
        return []
    snaps = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
    removed = []
    for old in snaps[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old)
    return removed


def sync_tree(src: Path, dest: Path) -> Path | None:
    """Replace dest with src, skipping caches and secrets.

    Anything this would delete or overwrite is moved into a timestamped snapshot
    first, via rsync's own --backup/--backup-dir, so a sync is recoverable
    instead of destructive. Returns the snapshot directory, or None if rsync was
    unavailable (in which case nothing was changed).

    Why this exists: dry-running the first ever sync against the live tree found
    five separate categories of machine-local state it would have destroyed --
    the hardware config, the authorized keys, the dist/ car zips, the CI
    credentials file, and 452 MB of _extract/ packaging intermediates. Each was
    fixed with an exclude once found. A snapshot makes the next one a recovery
    rather than a loss, because the list of things nobody thought to exclude is
    never knowably empty.
    """
    if not src.is_dir():
        raise FileNotFoundError(f"sync source missing: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    rsync = shutil.which("rsync")
    if rsync:
        dest.mkdir(parents=True, exist_ok=True)
        # utcnow() is second-resolution, and two syncs inside one second would
        # otherwise share a snapshot directory -- which breaks both the
        # one-snapshot-per-sync model and the empty-snapshot cleanup below.
        # Caught by running two syncs back to back in a test.
        stamp = utcnow().replace(":", "").replace("-", "")
        root = wipe_backup_root(dest)
        snapshot = root / stamp
        suffix = 1
        while snapshot.exists():
            snapshot = root / f"{stamp}.{suffix}"
            suffix += 1
        snapshot.mkdir(parents=True)
        cmd = [rsync, "-a", "--delete", "--backup", f"--backup-dir={snapshot}"]
        for pattern in RSYNC_EXCLUDES:
            cmd.extend(["--exclude", pattern])
        cmd.extend([str(src) + "/", str(dest) + "/"])
        subprocess.run(cmd, check=True)
        # An empty snapshot means the sync changed nothing; do not leave litter.
        if not any(snapshot.iterdir()):
            snapshot.rmdir()
            snapshot = None
        prune_wipe_backups(dest)
        return snapshot
    # No rsync: refuse rather than destroy. This fallback rmtree()s dest before
    # copying, so ignore_patterns cannot protect PRESERVE_LOCAL -- those files
    # are already deleted by the time copytree decides what to skip. Preserving
    # them here would mean copying them aside and restoring, which adds a
    # partial-restore failure mode to the one code path nobody exercises (rsync
    # is in environment.systemPackages and rsyncd runs on this host).
    #
    # Failing loudly is strictly better than a deploy that boots into the
    # hardware-configuration stub with no SSH keys.
    if dest.exists():
        raise RuntimeError(
            f"rsync not found on PATH, refusing to sync into existing {dest}. "
            "The non-rsync path cannot preserve machine-local files "
            f"({', '.join(PRESERVE_LOCAL)}); it would delete them and the next "
            "nixos-rebuild would fall back to the hardware-configuration stub "
            "with an empty authorized-keys list. Install rsync and retry."
        )
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
