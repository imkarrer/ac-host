#!/usr/bin/env python3
"""Send Series #1 PM poll via Discord REST (no gateway — safe while bot runs)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
from series_poll import FREEFORM, INTRO, POLLS, POLL_DURATION_HOURS  # noqa: E402

API = "https://discord.com/api/v10"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(token: str, method: str, path: str, payload: dict | None = None) -> dict | list:
    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "ac-host-poll-rest/1",
        "Content-Type": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
    try:
        body = urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    if not body:
        return {}
    return json.loads(body)


def open_dm(token: str, user_id: str) -> str:
    out = api(token, "POST", "/users/@me/channels", {"recipient_id": user_id})
    return str(out["id"])


def send_text(token: str, channel_id: str, content: str) -> None:
    api(token, "POST", f"/channels/{channel_id}/messages", {"content": content})


def send_poll(token: str, channel_id: str, question: str, answers: list[str]) -> None:
    api(
        token,
        "POST",
        f"/channels/{channel_id}/messages",
        {
            "poll": {
                "question": {"text": question[:300]},
                "answers": [{"poll_media": {"text": text[:55]}} for text in answers[:10]],
                "duration": POLL_DURATION_HOURS,
                "allow_multiselect": False,
            }
        },
    )


def main() -> None:
    env = load_env(Path("/var/lib/ac-host/.env"))
    if not env:
        env = load_env(ROOT / ".env")
    token = env.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN missing")
    user_ids = [
        x.strip()
        for x in env.get("DISCORD_PM_USER_IDS", "277926733989150727").split(",")
        if x.strip().isdigit()
    ]
    if not user_ids:
        raise SystemExit("DISCORD_PM_USER_IDS missing")

    sent = 0
    errors: list[str] = []
    for uid in user_ids:
        try:
            dm = open_dm(token, uid)
            send_text(token, dm, INTRO)
            time.sleep(0.5)
            for question, answers in POLLS:
                send_poll(token, dm, question, answers)
                time.sleep(0.6)
            send_text(token, dm, FREEFORM)
            sent += 1
            print(f"OK user={uid} channel={dm}")
        except Exception as exc:
            errors.append(f"{uid}: {exc}")
            print(f"FAIL user={uid} {exc}")
    print(f"done sent={sent} errors={len(errors)}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
