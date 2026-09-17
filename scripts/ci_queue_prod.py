#!/usr/bin/env python3
"""Stage the current checkout for the 03:00 apply. Safe: does not recycle."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "shared") not in sys.path:
    sys.path.insert(0, str(REPO / "shared"))

import pending_deploy  # noqa: E402


def main() -> int:
    state = pending_deploy.state_dir()
    if not pending_deploy.box_state_available(state):
        print(f"skip queue-prod: {state} is not a directory (agent is not on ac-box)")
        return 0

    sha = (os.environ.get("BUILDKITE_COMMIT") or "").strip() or "unknown"
    applied = pending_deploy.load_applied(state) or {}
    last = str(applied.get("sha") or "")
    changed = pending_deploy.git_changed_paths(REPO, last, sha if sha != "unknown" else "HEAD")
    rebuild = pending_deploy.rebuild_sidecars_from_diff(changed) if last else False
    # A recreate the last apply wanted but skipped (ci_downtime.py: image or
    # .env missing) is still owed, whatever this diff touched. Older stamps
    # have no key; they were written by a code path that never skipped.
    if last and not applied.get("sidecars_recreated", True):
        print(f"last apply {last} did not recreate the sidecars; recreating on this one")
        rebuild = True

    dest = pending_deploy.pending_src_dir(state)
    pending_deploy.sync_tree(REPO, dest)
    path = pending_deploy.write_pending(
        {
            "sha": sha,
            "queued_at": pending_deploy.utcnow(),
            "rebuild_sidecars": rebuild,
            "source": "buildkite",
            "build": os.environ.get("BUILDKITE_BUILD_URL", ""),
            "branch": os.environ.get("BUILDKITE_BRANCH", ""),
        },
        state,
    )
    print(f"queued {sha} rebuild_sidecars={rebuild} -> {path}")
    print(f"tree {dest}")
    print("folded into pending-src; bot 03:00 countdown applies once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
