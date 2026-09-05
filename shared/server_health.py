"""Practice-box health flag that the player page reads from leaderboard.json.

`maintenance.json` in AC_STATE is the operator switch. The plugin copies it onto
the board (`status` / `statusMessage`) and heartbeats `aliveAt` so an empty
lobby still looks online.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MESSAGE = "Practice servers are down for maintenance."
FLAG_NAME = "maintenance.json"
DOWN_STATUSES = frozenset({"down", "maintenance"})


def flag_path(state: Path) -> Path:
    return state / FLAG_NAME


def read_flag(state: Path) -> dict | None:
    path = flag_path(state)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"message": DEFAULT_MESSAGE}
    if isinstance(data, dict):
        return data
    return {"message": DEFAULT_MESSAGE}


def write_flag(state: Path, message: str = "") -> Path:
    path = flag_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"message": (message or DEFAULT_MESSAGE).strip()}, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def clear_flag(state: Path) -> None:
    path = flag_path(state)
    if path.is_file():
        path.unlink()


def apply_to_payload(payload: dict, state: Path) -> dict:
    flag = read_flag(state)
    if flag:
        payload["status"] = "maintenance"
        payload["statusMessage"] = str(flag.get("message") or DEFAULT_MESSAGE).strip() or DEFAULT_MESSAGE
    else:
        payload["status"] = "up"
        payload.pop("statusMessage", None)
    return payload


def is_down(payload: dict | None) -> bool:
    status = str((payload or {}).get("status") or "").strip().lower()
    return status in DOWN_STATUSES
