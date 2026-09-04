#!/usr/bin/env python3
"""3:00 AM America/Chicago practice recycle: session TIME, Discord, in-game chat.

Kunos has no wall-clock restart. Practice TIME is minutes from lobby start, so a
7pm bounce would otherwise kick everyone at 7pm the next day. We:

- set TIME to minutes until the next 03:00
- warn at 10m / 5m / 1m / 30s / 5s / 4 / 3 / 2 / 1
- systemd recycles containers at 03:00
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_AT = "03:00"
DEFAULT_TZ = "America/Chicago"

# Seconds before restart. 5–1 are one edited Discord message; earlier marks post.
COUNTDOWN_MARKS = (600, 300, 60, 30, 5, 4, 3, 2, 1, 0)
MENTION_MARKS = frozenset({600, 300, 60})
EDIT_MARKS = frozenset({5, 4, 3, 2, 1})


def zone_name() -> str:
    return os.environ.get("AC_TZ", DEFAULT_TZ).strip() or DEFAULT_TZ


def zone() -> ZoneInfo:
    return ZoneInfo(zone_name())


def restart_at_spec() -> str:
    raw = os.environ.get("PRACTICE_RESTART_AT", DEFAULT_AT).strip()
    if raw.lower() in ("", "off", "0", "none", "disabled"):
        return ""
    return raw


def parse_hhmm(spec: str) -> tuple[int, int] | None:
    spec = spec.strip()
    if not spec:
        return None
    parts = spec.split(":")
    if len(parts) != 2:
        raise ValueError(f"PRACTICE_RESTART_AT must be HH:MM, got {spec!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"PRACTICE_RESTART_AT out of range: {spec!r}")
    return hour, minute


def now_local(now: datetime | None = None) -> datetime:
    tz = zone()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def next_restart(now: datetime | None = None, *, spec: str | None = None) -> datetime | None:
    raw = restart_at_spec() if spec is None else spec
    parsed = parse_hhmm(raw) if raw else None
    if parsed is None:
        return None
    hour, minute = parsed
    current = now_local(now)
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current >= candidate:
        candidate += timedelta(days=1)
    return candidate


def seconds_until_restart(now: datetime | None = None) -> float | None:
    nxt = next_restart(now)
    if nxt is None:
        return None
    return (nxt - now_local(now)).total_seconds()


def practice_time_minutes(now: datetime | None = None) -> int:
    """Kunos [PRACTICE] TIME= so the session ends at the recycle, not +24h from start."""
    remaining = seconds_until_restart(now)
    if remaining is None:
        return 1440
    minutes = int(remaining // 60)
    if minutes < 1:
        return 1440
    return min(minutes, 1440)


def crossed_marks(prev: float | None, curr: float | None) -> list[int]:
    """Marks whose second-threshold was crossed while remaining counted down.

    A wrap to the next day's ~24h remaining fires any marks still below ``prev``
    (so 1s / 0s are not skipped when the clock rolls past 03:00).
    """
    if curr is None:
        return []
    if prev is None:
        return []
    if curr > prev + 60:
        return [mark for mark in COUNTDOWN_MARKS if prev > mark]
    hit: list[int] = []
    for mark in COUNTDOWN_MARKS:
        if prev > mark >= curr:
            hit.append(mark)
    return hit


def poll_timeout_sec(remaining: float | None) -> float:
    if remaining is None:
        return 5.0
    if remaining <= 15:
        return 0.2
    if remaining <= 600:
        return 1.0
    return 5.0


def label_for_mark(mark: int) -> str:
    if mark >= 60 and mark % 60 == 0:
        mins = mark // 60
        return f"{mins} minute" if mins == 1 else f"{mins} minutes"
    if mark > 0:
        return f"{mark} second" if mark == 1 else f"{mark} seconds"
    return "now"


def restart_clock_label(when: datetime | None = None) -> str:
    nxt = when if isinstance(when, datetime) else next_restart()
    if nxt is None:
        return "off"
    hour = nxt.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{nxt.strftime('%M %p')} CT"


def chat_text(mark: int) -> str:
    """In-game broadcast. Keep short — acServer truncates UTF chat."""
    if mark == 0:
        return "Server recycle now. Rejoin in a minute."
    if mark <= 5:
        return str(mark)
    if mark == 30:
        return "Server recycle in 30 seconds. Pit in."
    if mark == 60:
        return "Server recycle in 1 minute. You will be kicked."
    if mark == 300:
        return "Server recycle in 5 minutes (3:00 AM CT)."
    if mark == 600:
        return "Server recycle in 10 minutes (3:00 AM CT)."
    return f"Server recycle in {label_for_mark(mark)}."


def mention_ids(whitelist: dict, board: dict) -> list[str]:
    """Discord snowflakes for drivers currently in a lobby (skip discord_id=0)."""
    players = whitelist.get("players") or []
    by_steam = {
        str(player.get("steam_id") or ""): str(player.get("discord_id") or "")
        for player in players
        if player.get("enabled", True)
    }
    ids: list[str] = []
    seen: set[str] = set()
    for lobby in (board.get("lobbies") or {}).values():
        if not isinstance(lobby, dict):
            continue
        for driver in lobby.get("online") or []:
            guid = str(driver.get("guid") or "")
            did = by_steam.get(guid, "")
            if not did or did == "0" or did in seen:
                continue
            seen.add(did)
            ids.append(did)
    return ids


def online_lines(whitelist: dict, board: dict) -> list[str]:
    players = whitelist.get("players") or []
    by_steam = {str(player.get("steam_id") or ""): player for player in players}
    lines: list[str] = []
    for lobby in (board.get("lobbies") or {}).values():
        if not isinstance(lobby, dict):
            continue
        lobby_name = str(lobby.get("name") or lobby.get("id") or "lobby")
        for driver in lobby.get("online") or []:
            guid = str(driver.get("guid") or "")
            name = str(driver.get("name") or guid or "driver")
            player = by_steam.get(guid) or {}
            did = str(player.get("discord_id") or "")
            who = f"<@{did}>" if did and did != "0" else name
            lines.append(f"{who} — {lobby_name}")
    return lines


def discord_text(
    mark: int,
    *,
    online: list[str] | None = None,
    now: datetime | None = None,
) -> str:
    clock = restart_clock_label(next_restart(now))
    if mark == 0:
        body = f"**Lobbies restarting now** ({clock}). Rejoin in about a minute."
    elif mark <= 5:
        body = f"**{mark}**"
    elif mark == 30:
        body = f"Practice recycle in **30 seconds** ({clock}). You will be kicked."
    else:
        body = (
            f"Practice lobbies recycle in **{label_for_mark(mark)}** ({clock}). "
            "Session ends — rejoin after the restart."
        )
    if mark in MENTION_MARKS:
        if online:
            body += "\n\nIn a lobby now: " + ", ".join(online)
        else:
            body += "\n\nNobody in the lobbies right now."
    return body
