#!/usr/bin/env python3
"""Prove the containerized manifest can run every entrypoint compose names.

Run INSIDE ac-host-env by scripts/ci_containerize.sh, with this tree copied to
/repo (the path the manifest's [profile] builds PYTHONPATH from via AC_REPO),
the same way compose bind-mounts it in prod. A package missing from
.flox/env/manifest.toml then fails in CI, in the image that would have
shipped, rather than on ac-box at 03:00. Imports every module a compose
``command:`` starts, plus what the bot shells out to
(scripts/generate_series_liveries.py: numpy, scipy, Pillow and a scalable
font), and reports the Python and the font that resolved.
"""

from __future__ import annotations

import importlib
import sys

ENTRYPOINTS = (
    "bot",  # compose: bot
    "series_cmds",  # bot -> /series commands, shells out to the livery script
    "auth",  # compose: auth
    "details",  # compose: details
    "plugin",  # compose: plugin (imports series_lib from shared/ lazily)
    "push_status",
    "series_lib",
    "skin_livery",  # generate_series_liveries: needs numpy/scipy/PIL + font
    "generate_series_liveries",
)


def main() -> int:
    print(f"python {sys.version.split()[0]} at {sys.executable}")
    for name in ENTRYPOINTS:
        importlib.import_module(name)
        print(f"import ok: {name}")
    import skin_livery

    print(f"font: {skin_livery.find_font()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
