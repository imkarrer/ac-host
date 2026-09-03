#!/usr/bin/env python3
"""Content Manager extended-details HTTP for Kunos acServer.

CM only fetches this when the server name contains ℹ<port>.
The Online livery thumbnail row is bound to CurrentSessionType == Booking
(OnlineServer.xaml). Vanilla INFO reports Practice (type 1), so that row is
hidden and clicking the car only zooms the preview.

For /api/details, `session` is the session *type* (not an INFO index). Advertise
Booking (0) so the row appears, but keep pickup=true so Join is a direct
connect (acServer SUB returns FAILED_PICKUP on pickup lobbies).
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

# First unused pit's Skin becomes CM's AvailableSkin / Join CarSkinId.
PREFERRED_SKIN = {
    "abarth_124_2016": "02_Bianco",
    "tbb_toyota_gr86_premium": "04_trueno_blue",
    "pc_civic": "Championship White",
    "ks_mazda_miata": "02_crystal_white",
    "lotus_elise_sc": "0_racing_green",
    "bmw_m3_e30": "alpine_white",
}


def parse_ini_section(path: Path, section: str) -> dict[str, str]:
    data: dict[str, str] = {}
    current = ""
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if current != section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


def list_skins(content: Path, car: str) -> list[str]:
    skins = content / "cars" / car / "skins"
    if not skins.is_dir():
        return []
    names = []
    for path in sorted(skins.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        # CM paint overlay — no online textures; Join would spawn default Rosso.
        if "owner_white" in path.name.lower():
            continue
        if (
            (path / "ui_skin.json").is_file()
            or (path / "preview.jpg").is_file()
            or (path / "skin.ini").is_file()
        ):
            names.append(path.name)
    return names


def load_json_url(url: str) -> dict:
    try:
        with urlopen(url, timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def load_info(http_port: int) -> dict:
    return load_json_url(f"http://127.0.0.1:{http_port}/INFO")


def load_players(http_port: int, guid: str) -> list[dict]:
    steam = guid.strip() or "-1"
    data = load_json_url(f"http://127.0.0.1:{http_port}/JSON|{steam}")
    cars = data.get("Cars") if isinstance(data, dict) else None
    return list(cars) if isinstance(cars, list) else []


def parse_entry_list(path: Path) -> list[dict]:
    slots: list[dict] = []
    if not path.is_file():
        return slots
    current: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            if current.get("MODEL"):
                slots.append(slot_from_entry(current))
            current = {}
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        current[key.strip()] = value.strip()
    if current.get("MODEL"):
        slots.append(slot_from_entry(current))
    return slots


def slot_from_entry(entry: dict[str, str]) -> dict:
    return {
        "Model": entry.get("MODEL") or "",
        "Skin": entry.get("SKIN") or "",
        "IsConnected": False,
        "IsEntryList": True,
        "IsRequestedGUID": False,
        "DriverName": entry.get("DRIVERNAME") or "",
        "DriverTeam": entry.get("TEAM") or "",
    }


def fill_empty_skins(slots: list[dict], content: Path) -> list[dict]:
    """CM Join writes AvailableSkin from the first free pit. Empty SKIN= maps to
    the car's first folder (Rosso / Fusion Orange). Fill a real default instead.
    """
    known: dict[str, list[str]] = {}
    filled = []
    for slot in slots:
        item = dict(slot)
        model = item.get("Model") or ""
        connected = bool(item.get("IsConnected"))
        skin = (item.get("Skin") or "").strip()
        if not connected and not skin and model:
            if model not in known:
                known[model] = list_skins(content, model)
            preferred = PREFERRED_SKIN.get(model)
            if preferred and preferred in known[model]:
                item["Skin"] = preferred
            elif known[model]:
                item["Skin"] = known[model][0]
        filled.append(item)
    return filled


def load_cm_content(track_folder: str = "", *, state: Path | None = None) -> dict:
    """Shape content.json for CM Online: cars map + singular track for this lobby.

    CM reads content.cars[id].url and content.track.url. A tracks{} map is
    ignored. See ServerEntry.Extended.cs InstallMissingContentTasks.
    """
    root = state or Path(os.environ.get("AC_STATE", "/data"))
    path = root / "dist" / "content.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    cars = data.get("cars")
    if isinstance(cars, dict):
        out["cars"] = cars
    if isinstance(data.get("track"), dict) and "url" in data["track"]:
        out["track"] = data["track"]
    tracks = data.get("tracks")
    folder = (track_folder or "").strip()
    if isinstance(tracks, dict) and folder and isinstance(tracks.get(folder), dict):
        out["track"] = tracks[folder]
    return out


def details_payload(
    cfg_dir: Path, content: Path, details_port: int, guid: str = ""
) -> dict:
    server = parse_ini_section(cfg_dir / "server_cfg.ini", "SERVER")
    http_port = int(server.get("HTTP_PORT") or 8081)
    info = load_info(http_port)
    cars = [c for c in (server.get("CARS") or "").split(";") if c]
    if not cars:
        cars = list(info.get("cars") or [])
    slots = load_players(http_port, guid)
    if not slots:
        slots = parse_entry_list(cfg_dir / "entry_list.ini")
    slots = fill_empty_skins(slots, content)
    timeleft = info.get("timeleft") if info.get("timeleft") is not None else 86400
    payload = {
        "ip": info.get("ip") or "",
        "port": int(server.get("UDP_PORT") or info.get("port") or 9600),
        "cport": http_port,
        "tport": int(server.get("TCP_PORT") or info.get("tport") or server.get("UDP_PORT") or 9600),
        "name": server.get("NAME") or info.get("name") or "",
        "clients": info.get("clients") or 0,
        "maxclients": int(server.get("MAX_CLIENTS") or info.get("maxclients") or 24),
        "track": server.get("TRACK") or info.get("track") or "",
        "cars": cars,
        "timeofday": info.get("timeofday") if info.get("timeofday") is not None else 48,
        # Type 0 = Booking. CM OnlineServer.xaml only shows the skin strip then.
        "session": 0,
        "sessiontypes": [0],
        "durations": [int(timeleft)],
        "timeleft": timeleft,
        "country": info.get("country") or ["na", "na"],
        "pass": False,
        "pickup": True,
        "timed": True,
        "extra": True,
        "inverted": 0,
        "l": True,
        "wrappedPort": details_port,
        "until": 0,
        "players": {"Cars": slots},
        "content": load_cm_content(server.get("TRACK") or info.get("track") or ""),
        "description": (
            "Online livery thumbnails are cosmetic on this pickup server — "
            "spawn uses the pit default (Bianco / Trueno Blue / Championship White).\n"
            + (
                os.environ.get("AC_PAGES_URL")
                or os.environ.get("AC_CONTENT_URL")
                or ""
            )
        ),
    }
    return payload


class DetailsHandler(BaseHTTPRequestHandler):
    server_version = "ac-host-details/1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/health", "/"):
            self._write(200, b"ok\n", "text/plain; charset=utf-8")
            return
        if path != "/api/details":
            self.send_error(404)
            return
        guid = (parse_qs(parsed.query).get("guid") or [""])[0]
        body = json.dumps(
            details_payload(
                self.server.cfg_dir,
                self.server.content,
                self.server.details_port,
                guid,
            )
        ).encode("utf-8")
        self._write(200, body, "application/json; charset=utf-8")

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}")


class DetailsServer(ThreadingHTTPServer):
    def __init__(self, port: int, cfg_dir: Path, content: Path):
        super().__init__(("0.0.0.0", port), DetailsHandler)
        self.cfg_dir = cfg_dir
        self.content = content
        self.details_port = port


def discover(state: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for cfg in sorted(state.glob("static/*/cfg")) + sorted(state.glob("races/*/cfg")):
        server = parse_ini_section(cfg / "server_cfg.ini", "SERVER")
        http_port = server.get("HTTP_PORT")
        if not http_port:
            continue
        found.append((int(http_port) + 100, cfg))
    return found


def main() -> None:
    state = Path(os.environ.get("AC_STATE", "/data"))
    content = Path(os.environ.get("AC_CONTENT", "/content"))
    servers = []
    for port, cfg_dir in discover(state):
        httpd = DetailsServer(port, cfg_dir, content)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        servers.append((port, cfg_dir, httpd, thread))
        print(f"details {cfg_dir.parent.name} on {port}")
    if not servers:
        raise SystemExit(f"no cfg under {state}/static or {state}/races")
    servers[0][3].join()


if __name__ == "__main__":
    main()
