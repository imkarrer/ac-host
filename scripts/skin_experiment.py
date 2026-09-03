#!/usr/bin/env python3
"""Re-render the dev lobby entry_list for livery-picker experiments A–D.

Does not touch production lobbies. Restarts only the dev static container.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EXPERIMENTS = {
    "A": ("pinned", "Baseline: every pit pinned to PREFERRED_SKIN (02_Bianco on 124)."),
    "B": ("empty", "Empty SKIN= — click Nero in CM lobby row, then Join; read race.ini SKIN=."),
    "C": ("empty", "Same as B but pick livery on Content → Cars first, then Join without row click."),
    "D": ("cycle", "Unique skin per pit (first joiner gets pit 0 color)."),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=sorted(EXPERIMENTS), help="Experiment id from the plan")
    parser.add_argument("--env", default="dev", choices=("dev",), help="Only dev is supported")
    args = parser.parse_args()

    skin_mode, note = EXPERIMENTS[args.experiment]
    os.environ["RENDER_SKIN_MODE"] = skin_mode

    acctl = REPO / "scripts" / "acctl.py"
    print(f"Experiment {args.experiment}: {note}")
    print(f"RENDER_SKIN_MODE={skin_mode}")
    print()

    # Re-render and restart dev lobby only (kicks anyone on dev-blackhawk, not prod).
    subprocess.run(
        [sys.executable, str(acctl), "--env", "dev", "up-static", "--only", "dev-blackhawk"],
        check=True,
        cwd=str(REPO),
    )

    print()
    print("After Join from Content Manager:")
    print("  1. Check Documents/Assetto Corsa/cfg/race.ini → [CAR_0] SKIN=")
    print("  2. Note spawned livery in-game")
    print("  3. ssh ac-box 'docker logs ac-dev-static-dev-blackhawk 2>&1 | tail -20'")
    print()
    print("Dev join INFO uses AC_PUBLIC_IP:8089 (set in .env)")
    print("Details: curl -s http://127.0.0.1:8189/api/details | python3 -m json.tool")


if __name__ == "__main__":
    main()
