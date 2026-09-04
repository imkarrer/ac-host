"""Build a Discord snapshot of the practice player page (join links first)."""

from __future__ import annotations

import json
import os
from pathlib import Path

HTTP_START = 8081
MARKER = "fugazy-page"
EMBED_COLOR = 0xE11D2E

# Same card labels as site/index.html join-grid.
SHORT_LABELS = {
    "blackhawk": "Blackhawk",
    "road-america": "Road America",
    "gingerman": "Gingerman",
    "dev-blackhawk": "DEV Blackhawk",
}

# Same folders as scripts/content_manifest.PRACTICE_TRACKS (bot image has no scripts/).
TRACK_ZIPS = (
    ("Blackhawk", "slipangle_ggt"),
    ("Road America", "lilski_road_america"),
    ("Gingerman", "gingerman_raceway"),
)


def track_zip_url(folder: str) -> str:
    owner = os.environ.get("AC_GITHUB_OWNER", "imkarrer").strip() or "imkarrer"
    repo = os.environ.get("AC_GITHUB_REPO", "ac-practice").strip() or "ac-practice"
    return f"https://github.com/{owner}/{repo}/releases/download/content/{folder}.zip"


def track_downloads() -> list[dict]:
    return [{"label": label, "url": track_zip_url(folder)} for label, folder in TRACK_ZIPS]


def join_url(public_ip: str, http_port: int) -> str:
    return f"https://acstuff.ru/s/q:race/online/join?ip={public_ip}&httpPort={http_port}"


def load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data if isinstance(data, dict) else default


def load_statics(path: Path) -> list[dict]:
    data = load_json(path, {"lobbies": []})
    lobbies = data.get("lobbies") or []
    return [item for item in lobbies if isinstance(item, dict)]


def short_label(lobby: dict) -> str:
    lobby_id = str(lobby.get("id") or "")
    if lobby_id in SHORT_LABELS:
        return SHORT_LABELS[lobby_id]
    name = str(lobby.get("name") or lobby_id)
    if "—" in name:
        name = name.split("—", 1)[1].strip()
    return name or lobby_id


def online_drivers(lobby: dict | None) -> list[dict]:
    if not lobby:
        return []
    rows = lobby.get("online") or []
    return [row for row in rows if isinstance(row, dict)]


def online_label(online: list[dict]) -> str:
    if not online:
        return "empty"
    if len(online) == 1:
        return str(online[0].get("name") or "1 online")
    return f"{len(online)} online"


def driver_names(online: list[dict]) -> str:
    names = [str(row.get("name") or "").strip() for row in online]
    return ", ".join(name for name in names if name)


def practice_lobbies(statics: list[dict]) -> list[dict]:
    out = []
    for item in statics:
        lobby_id = str(item.get("id") or "")
        if lobby_id.startswith("race-") or lobby_id.startswith("slot-"):
            continue
        out.append(item)
    return out


def lobby_rows(statics: list[dict], board: dict, public_ip: str) -> list[dict]:
    lobbies = (board or {}).get("lobbies") or {}
    rows = []
    for item in practice_lobbies(statics):
        try:
            slot = int(item.get("slot"))
        except (TypeError, ValueError):
            continue
        lobby_id = str(item.get("id") or "")
        online = online_drivers(lobbies.get(lobby_id) if isinstance(lobbies.get(lobby_id), dict) else None)
        rows.append(
            {
                "id": lobby_id,
                "label": short_label(item),
                "name": str(item.get("name") or lobby_id),
                "http_port": HTTP_START + slot,
                "join": join_url(public_ip, HTTP_START + slot),
                "online": online,
                "status": online_label(online),
                "names": driver_names(online),
                "busy": bool(online),
            }
        )
    return rows


def pages_href(pages_url: str) -> str:
    return (pages_url or "").strip().rstrip("/") + "/"


def snapshot(
    *,
    statics: list[dict],
    board: dict,
    public_ip: str,
    pages_url: str,
    cars: list[str],
) -> dict:
    """JSON-serializable payload the bot turns into an embed + link buttons."""
    rows = lobby_rows(statics, board, public_ip)
    updated = str((board or {}).get("updated") or "").strip()
    href = pages_href(pages_url)
    fields = []
    for row in rows:
        value = row["status"]
        if row["busy"] and row["names"] and row["status"] != row["names"]:
            value = f"{row['status']} — {row['names']}"
        fields.append({"name": row["label"], "value": value or "empty", "inline": True})
    if cars:
        fields.append({"name": "Garage", "value": " · ".join(cars), "inline": False})
    zips = track_downloads()
    if zips:
        fields.append(
            {
                "name": "Tracks",
                "value": " · ".join(f"[{item['label']}]({item['url']})" for item in zips),
                "inline": False,
            }
        )
    buttons = [{"label": row["label"], "url": row["join"]} for row in rows]
    if href:
        buttons.append({"label": "Player page", "url": href})
    description = (
        "Same join links as the player page. Approved Steam IDs only. "
        "After join: **Download missing content**.\n"
        "empty = nobody in the lobby. A name / N online = someone’s already in.\n"
        "Track zips are in the Tracks field (or on the player page)."
    )
    if href:
        description += f"\n{href}"
    stamp = updated.replace("T", " ").replace("+00:00", " UTC") if updated else "waiting for first lap / join"
    return {
        "title": "Practice",
        "description": description,
        "color": EMBED_COLOR,
        "url": href or None,
        "fields": fields,
        "footer": f"{MARKER} · Updated {stamp}",
        "buttons": buttons,
    }
