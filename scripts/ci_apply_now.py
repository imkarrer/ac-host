#!/usr/bin/env python3
"""Ask systemd to apply-now. The agent only writes a file — no Docker, no SSH."""

from __future__ import annotations

import json
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
        print(f"skip apply-now: {state} is not a directory")
        return 0
    if pending_deploy.load_pending(state) is None:
        print("no pending-deploy.json; nothing to apply")
        return 0
    path = state / "apply-now.json"
    path.write_text(
        json.dumps(
            {
                "requested_at": pending_deploy.utcnow(),
                "build": os.environ.get("BUILDKITE_BUILD_URL", ""),
                "message": os.environ.get(
                    "AC_APPLY_MESSAGE",
                    "Practice servers are restarting for a deploy.",
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {path} — ac-host-apply-now.path will drain/resume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
