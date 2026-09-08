"""Atomic JSON read/write for files several processes share.

Nine files in this repo write ``leaderboard.json``: acctl.py,
ci_publish_pages.py, seed_github_env.py, series_lib.py, plugin.py,
push_status.py, bot.py and server_health.py. Before this module, none of them
used ``os.replace`` and nothing used a lock, so every one of them was a
truncate-then-write against a file the others were reading.

Two failure modes that follow from that, both observed in the code rather than
theorised:

1. A reader can see a half-written file, because ``Path.write_text`` truncates
   first and the content arrives afterwards.
2. Worse, a writer that reacts to unparseable JSON by starting from ``{}`` will
   then write that empty object back, converting a transient read error into
   permanent data loss. ``acctl.publish_health`` did exactly this on every boot.

``read_json`` therefore distinguishes "absent" from "unreadable" instead of
collapsing both to an empty dict, and leaves the caller to decide. Losing a
community's race standings should never be the default branch.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class UnreadableJSON(Exception):
    """The file exists but could not be parsed as a JSON object.

    Deliberately distinct from absence. A caller that wants to merge into
    existing data must not treat this as "start fresh".
    """


def read_json(path: Path) -> dict[str, Any] | None:
    """Return the object, or None if the file does not exist.

    Raises UnreadableJSON if it exists but cannot be parsed, or parses to
    something other than an object.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UnreadableJSON(f"{path} could not be read: {exc}") from exc
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnreadableJSON(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise UnreadableJSON(f"{path} holds {type(loaded).__name__}, expected an object")
    return loaded


def write_json(path: Path, payload: dict[str, Any]) -> str:
    """Write payload to path atomically. Returns the serialised text.

    The temporary file is created in the destination directory so that
    os.replace is a same-filesystem rename, which is atomic. A reader either
    sees the old file complete or the new file complete, never a partial one.
    """
    text = json.dumps(payload, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            # Without this the rename can land before the bytes do, so a crash
            # leaves an empty-but-present file -- which is the corrupt input that
            # started this whole problem.
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return text
