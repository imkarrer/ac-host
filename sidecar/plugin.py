#!/usr/bin/env python3
"""UDP plugin: persist practice best laps and live occupancy per lobby."""

from __future__ import annotations

import json
import os
import select
import socket
import struct
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE, _HERE.parent / "shared"):
    if (_candidate / "downtime.py").is_file() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
        break

HEARTBEAT_SEC = float(os.environ.get("STATUS_HEARTBEAT_SEC", "60"))

# Must match scripts/render_cfg.py and scripts/acctl.py
GAME_PORT_START = 9600
HTTP_PORT_START = 8081
PLUGIN_LOCAL_START = 11200
PLUGIN_EVENT_START = 11300
SLOT_COUNT_DEFAULT = 16
MAX_CAR_ID = 24
MIN_LAP_MS = 30_000

ACSP_NEW_SESSION = 50
ACSP_NEW_CONNECTION = 51
ACSP_CONNECTION_CLOSED = 52
ACSP_CAR_INFO = 54
ACSP_END_SESSION = 55
ACSP_VERSION = 56
ACSP_CLIENT_LOADED = 58
ACSP_SESSION_INFO = 59
ACSP_LAP_COMPLETED = 73
ACSP_GET_CAR_INFO = 201
ACSP_SEND_CHAT = 202
ACSP_BROADCAST_CHAT = 203
ACSP_GET_SESSION_INFO = 204


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def remaining(self) -> int:
        return len(self.data) - self.offset

    def _need(self, n: int) -> None:
        if self.remaining() < n:
            raise ValueError("short packet")

    def u8(self) -> int:
        self._need(1)
        value = self.data[self.offset]
        self.offset += 1
        return value

    def u16(self) -> int:
        self._need(2)
        value = struct.unpack_from("<H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def u32(self) -> int:
        self._need(4)
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def i32(self) -> int:
        self._need(4)
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def ascii(self) -> str:
        length = self.u8()
        self._need(length)
        raw = self.data[self.offset : self.offset + length]
        self.offset += length
        return raw.decode("utf-8", errors="replace")

    def utf(self) -> str:
        length = self.u8()
        nbytes = length * 4
        self._need(nbytes)
        raw = self.data[self.offset : self.offset + nbytes]
        self.offset += nbytes
        return raw.decode("utf-32-le", errors="replace").replace("\x00", "").strip()


def write_utf(text: str) -> bytes:
    encoded = text.encode("utf-32-le")
    return bytes([len(encoded) // 4]) + encoded


def write_ascii(text: str) -> bytes:
    encoded = text.encode("ascii", errors="replace")
    return bytes([len(encoded)]) + encoded


def pack_broadcast_chat(text: str) -> bytes:
    """ACSP_BROADCAST_CHAT (203) + UTF-32 string. Truncate so u8 length fits."""
    clipped = (text or "")[:200]
    return bytes([ACSP_BROADCAST_CHAT]) + write_utf(clipped)


def parse_lap_completed(payload: bytes) -> tuple[int, int, int]:
    reader = Reader(payload)
    car_id = reader.u8()
    laptime = reader.u32()
    cuts = reader.u8()
    return car_id, laptime, cuts


def parse_new_connection(payload: bytes) -> dict:
    reader = Reader(payload)
    name = reader.utf()
    guid = reader.utf().strip()
    car_id = reader.u8()
    car = reader.ascii()
    skin = reader.ascii()
    return {"name": name, "guid": guid, "car_id": car_id, "car": car, "skin": skin}


def parse_connection_closed(payload: bytes) -> dict:
    return parse_new_connection(payload)


def parse_car_info(payload: bytes) -> dict:
    reader = Reader(payload)
    car_id = reader.u8()
    connected = reader.u8() != 0
    car = reader.utf()
    skin = reader.utf()
    name = reader.utf()
    team = reader.utf()
    guid = reader.utf().strip()
    return {
        "car_id": car_id,
        "connected": connected,
        "car": car,
        "skin": skin,
        "name": name,
        "team": team,
        "guid": guid,
    }


def parse_session_info(payload: bytes) -> dict:
    reader = Reader(payload)
    protocol = reader.u8()
    session_index = reader.u8()
    current_session_index = reader.u8()
    session_count = reader.u8()
    server_name = reader.utf()
    track = reader.ascii()
    track_config = reader.ascii()
    name = reader.ascii()
    typ = reader.u8()
    time = reader.u16()
    laps = reader.u16()
    wait_time = reader.u16()
    ambient = reader.u8()
    road = reader.u8()
    weather = reader.ascii()
    elapsed_ms = reader.i32() if reader.remaining() >= 4 else 0
    return {
        "protocol": protocol,
        "session_index": session_index,
        "current_session_index": current_session_index,
        "session_count": session_count,
        "server_name": server_name,
        "track": track,
        "track_config": track_config,
        "name": name,
        "typ": typ,
        "time": time,
        "laps": laps,
        "wait_time": wait_time,
        "ambient": ambient,
        "road": road,
        "weather": weather,
        "elapsed_ms": elapsed_ms,
    }


def entry_key(guid: str, car: str) -> tuple[str, str]:
    return guid, car


def sort_entries(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda item: (int(item["ms"]), str(item.get("at") or "")))


def upsert_entry(entries: list[dict], entry: dict) -> bool:
    """Insert or replace a personal best. Refresh name even when the time is not a PB."""
    key = entry_key(entry["guid"], entry["car"])
    for old in entries:
        if entry_key(old["guid"], old["car"]) != key:
            continue
        old["name"] = entry["name"]
        if int(entry["ms"]) < int(old["ms"]):
            old["ms"] = entry["ms"]
            old["at"] = entry["at"]
            old["carName"] = entry.get("carName") or old.get("carName")
            return True
        return False
    entries.append(entry)
    return True


def valid_lap(ms: int, cuts: int, guid: str) -> bool:
    return bool(guid) and cuts == 0 and MIN_LAP_MS <= ms <= 30 * 60 * 1000


def load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data if isinstance(data, dict) else default


def load_car_names(catalog: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    cars = catalog / "cars"
    if not cars.is_dir():
        return names
    for path in cars.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        folder = str(data.get("folder") or path.stem)
        names[folder] = str(data.get("displayName") or folder)
    return names


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


def slot_from_cfg(cfg_dir: Path) -> int | None:
    """Derive acctl slot index from a rendered server_cfg.ini."""
    server = parse_ini_section(cfg_dir / "server_cfg.ini", "SERVER")
    if server.get("UDP_PORT"):
        return int(server["UDP_PORT"]) - GAME_PORT_START
    if server.get("HTTP_PORT"):
        return int(server["HTTP_PORT"]) - HTTP_PORT_START
    return None


def max_cars_for_slot(state: Path, slot: int) -> int:
    """How many pit slots acServer actually has for this lobby.

    GET_CAR_INFO past MAX_CLIENTS-1 logs `requested CAR INFO for car N not present`.
    """
    for cfg in sorted(state.glob("static/*/cfg")) + sorted(state.glob("races/*/cfg")):
        if slot_from_cfg(cfg) != slot:
            continue
        server = parse_ini_section(cfg / "server_cfg.ini", "SERVER")
        try:
            n = int(server.get("MAX_CLIENTS") or MAX_CAR_ID)
        except ValueError:
            n = MAX_CAR_ID
        return max(1, min(MAX_CAR_ID, n))
    return MAX_CAR_ID


def load_statics(catalog: Path) -> list[dict]:
    name = os.environ.get("AC_CATALOG_STATICS", "statics.json")
    path = catalog / name
    data = load_json(path, {"lobbies": []})
    return list(data.get("lobbies") or [])


def resolve_plugin_slots(state: Path, catalog: Path) -> list[int]:
    """UDP listener slots for this plugin process (host network — no overlap across envs)."""
    override = os.environ.get("PLUGIN_SLOTS", "").strip()
    if override:
        return sorted({int(part.strip()) for part in override.split(",") if part.strip()})

    slots: set[int] = set()
    for item in load_statics(catalog):
        slots.add(int(item["slot"]))

    races = load_json(state / "slots.json", {})
    if isinstance(races, dict):
        for info in races.values():
            if isinstance(info, dict) and info.get("slot") is not None:
                slots.add(int(info["slot"]))

    for cfg in sorted(state.glob("static/*/cfg")) + sorted(state.glob("races/*/cfg")):
        slot = slot_from_cfg(cfg)
        if slot is not None and slot >= 0:
            slots.add(slot)

    for meta_path in sorted(state.glob("series/*/rounds/*/quali/meta.json")):
        meta = load_json(meta_path, {})
        if meta.get("slot") is not None:
            slots.add(int(meta["slot"]))
    for cfg in sorted(state.glob("series/*/rounds/*/*/cfg")):
        slot = slot_from_cfg(cfg)
        if slot is not None and slot >= 0:
            slots.add(slot)

    return sorted(slots)


def series_quali_meta(state: Path, slot: int) -> dict | None:
    for meta_path in state.glob("series/*/rounds/*/quali/meta.json"):
        meta = load_json(meta_path, {})
        if int(meta.get("slot") or -1) == slot:
            return meta
    return None


def sync_series_quali_lap(
    state: Path,
    series_id: str,
    round_id: str,
    *,
    steam_id: str,
    lap_ms: int,
) -> None:
    shared = Path(__file__).resolve().parents[1] / "shared"
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    import series_lib

    series_lib.record_quali_lap(
        state,
        series_id,
        round_id,
        steam_id=steam_id,
        lap_ms=lap_ms,
    )


def empty_lobby(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item.get("name") or item["id"],
        "track": item.get("track") or "",
        "sessionStarted": None,
        "online": [],
        "allTime": [],
        "session": [],
    }


def normalize_online(drivers: list[dict], car_names: dict[str, str]) -> list[dict]:
    cleaned: list[dict] = []
    for driver in drivers:
        car = str(driver.get("car") or "")
        guid = str(driver.get("guid") or "")
        cleaned.append(
            {
                "guid": guid,
                "name": str(driver.get("name") or guid or "—"),
                "car": car,
                "carName": car_names.get(car) or car,
            }
        )
    return sorted(cleaned, key=lambda item: (item["name"].lower(), item["guid"]))


class Leaderboard:
    def __init__(self, *, path: Path, dist: Path, statics: list[dict], car_names: dict[str, str]) -> None:
        self.path = path
        self.dist = dist
        self.statics = statics
        self.car_names = car_names
        self.payload = self._load()

    def _load(self) -> dict:
        payload = load_json(self.path, {"updated": None, "lobbies": {}})
        existing = payload.get("lobbies") or {}
        ordered: dict[str, dict] = {}
        for item in self.statics:
            current = existing.get(item["id"])
            if not isinstance(current, dict):
                ordered[item["id"]] = empty_lobby(item)
                continue
            current.setdefault("id", item["id"])
            current["name"] = item.get("name") or current.get("name") or item["id"]
            current["track"] = item.get("track") or current.get("track") or ""
            current.setdefault("sessionStarted", None)
            current.setdefault("online", [])
            current.setdefault("allTime", [])
            current.setdefault("session", [])
            ordered[item["id"]] = current
        for key, value in existing.items():
            if key not in ordered and isinstance(value, dict):
                if key.startswith("race-") or key.startswith("slot-") or key.startswith("series-"):
                    ordered[key] = value
        payload["lobbies"] = ordered
        try:
            import server_health

            server_health.apply_to_payload(payload, self.path.parent)
        except Exception:
            pass
        return payload

    def _apply_health(self) -> None:
        try:
            import server_health

            server_health.apply_to_payload(self.payload, self.path.parent)
        except Exception:
            pass

    def save(self) -> None:
        self._apply_health()
        self.payload["aliveAt"] = utcnow()
        self.payload["updated"] = utcnow()
        for lobby in self.payload["lobbies"].values():
            lobby["allTime"] = sort_entries(list(lobby.get("allTime") or []))
            lobby["session"] = sort_entries(list(lobby.get("session") or []))
        text = json.dumps(self.payload, indent=2) + "\n"
        atomic_write(self.path, text)
        atomic_write(self.dist, text)
        try:
            from push_status import schedule_push

            schedule_push(text)
        except Exception:
            pass

    def touch_alive(self) -> None:
        """Refresh aliveAt (and ntfy) without a GitHub commit unless status flipped."""
        before = (self.payload.get("status"), self.payload.get("statusMessage"))
        self._apply_health()
        self.payload["aliveAt"] = utcnow()
        after = (self.payload.get("status"), self.payload.get("statusMessage"))
        text = json.dumps(self.payload, indent=2) + "\n"
        atomic_write(self.path, text)
        atomic_write(self.dist, text)
        try:
            if before != after:
                from push_status import schedule_push

                schedule_push(text)
            else:
                from push_status import notify_heartbeat

                notify_heartbeat()
        except Exception:
            pass

    def lobby(self, lobby_id: str, *, name: str = "", track: str = "") -> dict:
        lobbies = self.payload.setdefault("lobbies", {})
        if lobby_id not in lobbies:
            lobbies[lobby_id] = empty_lobby({"id": lobby_id, "name": name or lobby_id, "track": track})
        return lobbies[lobby_id]

    def reset_session(self, lobby_id: str, *, name: str = "", track: str = "") -> None:
        lobby = self.lobby(lobby_id, name=name, track=track)
        lobby["session"] = []
        lobby["sessionStarted"] = utcnow()
        self.save()

    def clear_online(self) -> None:
        """Drop disk occupancy so a restart cannot show stale drivers."""
        for lobby in self.payload["lobbies"].values():
            lobby["online"] = []

    def set_online(self, lobby_id: str, drivers: list[dict], *, name: str = "", track: str = "") -> bool:
        lobby = self.lobby(lobby_id, name=name, track=track)
        cleaned = normalize_online(drivers, self.car_names)
        if lobby.get("online") == cleaned:
            return False
        lobby["online"] = cleaned
        self.save()
        return True

    def record(self, lobby_id: str, *, guid: str, name: str, car: str, ms: int, cuts: int) -> bool:
        if not valid_lap(ms, cuts, guid):
            return False
        entry = {
            "guid": guid,
            "name": name or guid,
            "car": car,
            "carName": self.car_names.get(car) or car,
            "ms": ms,
            "at": utcnow(),
        }
        lobby = self.lobby(lobby_id)
        changed = upsert_entry(lobby["allTime"], dict(entry))
        changed = upsert_entry(lobby["session"], dict(entry)) or changed
        self.save()
        return changed


def slot_to_lobby_id(slot: int, statics: list[dict], races: dict, *, state: Path | None = None) -> str:
    for item in statics:
        if int(item.get("slot", -1)) == slot:
            return str(item["id"])
    for name, info in races.items():
        if int(info.get("slot", -1)) == slot:
            if str(info.get("kind") or "") == "series":
                return f"series-{info.get('series_id')}-{info.get('round_id')}-{info.get('phase')}"
            return f"race-{name}"
    if state is not None:
        meta = series_quali_meta(state, slot)
        if meta:
            return f"series-{meta['series_id']}-{meta['round_id']}-quali"
        for phase in ("race", "quali"):
            for meta_path in state.glob(f"series/*/rounds/*/{phase}/meta.json"):
                meta = load_json(meta_path, {})
                if int(meta.get("slot") or -1) == slot:
                    return f"series-{meta['series_id']}-{meta['round_id']}-{phase}"
    return f"slot-{slot}"


def lobby_meta(lobby_id: str, statics: list[dict]) -> dict:
    for item in statics:
        if item["id"] == lobby_id:
            return item
    return {"id": lobby_id, "name": lobby_id, "track": ""}


class Plugin:
    def __init__(
        self,
        *,
        state: Path,
        catalog: Path,
        dist: Path,
        host: str = "127.0.0.1",
        slots: list[int] | None = None,
    ) -> None:
        self.host = host
        self.state = state
        self.statics = load_statics(catalog)
        self.slots = slots if slots is not None else resolve_plugin_slots(state, catalog)
        races = load_json(state / "slots.json", {})
        self.races = races if isinstance(races, dict) else {}
        self.board = Leaderboard(
            path=state / "leaderboard.json",
            dist=dist / "leaderboard.json",
            statics=self.statics,
            car_names=load_car_names(catalog),
        )
        self.cars: dict[int, dict[int, dict]] = {}
        self.socks: dict[socket.socket, int] = {}
        self.slot_sock: dict[int, socket.socket] = {}
        self._downtime_prev: float | None = None
        self._last_heartbeat: float = 0.0
        self.board.clear_online()
        self.board.save()

    def bind(self) -> None:
        if not self.slots:
            print("plugin: no slots to bind (set PLUGIN_SLOTS or render lobbies first)")
            return
        for slot in self.slots:
            event_port = PLUGIN_EVENT_START + slot
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind((self.host, event_port))
            except OSError as exc:
                print(f"plugin slot {slot} bind {event_port} failed: {exc}")
                sock.close()
                continue
            self.socks[sock] = slot
            self.slot_sock[slot] = sock
            print(f"plugin slot {slot} listening {self.host}:{event_port} -> {self.host}:{PLUGIN_LOCAL_START + slot}")
            self.ask_session(slot)
            self.ask_all_cars(slot)

    def send(self, slot: int, payload: bytes) -> None:
        sock = self.slot_sock.get(slot)
        if sock is None:
            return
        try:
            sock.sendto(payload, (self.host, PLUGIN_LOCAL_START + slot))
        except OSError as exc:
            print(f"plugin send slot {slot} failed: {exc}")

    def broadcast_chat(self, text: str) -> None:
        payload = pack_broadcast_chat(text)
        for slot in list(self.slot_sock):
            self.send(slot, payload)
        print(f"plugin chat: {text}")

    def tick_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat < HEARTBEAT_SEC:
            return
        self._last_heartbeat = now
        self.board.touch_alive()

    def tick_downtime(self) -> None:
        try:
            import downtime
        except ImportError:
            return
        remaining = downtime.seconds_until_restart()
        for mark in downtime.crossed_marks(self._downtime_prev, remaining):
            self.broadcast_chat(downtime.chat_text(mark))
        self._downtime_prev = remaining

    def poll_timeout(self) -> float:
        try:
            import downtime
        except ImportError:
            return 5.0
        return downtime.poll_timeout_sec(downtime.seconds_until_restart())

    def ask_car(self, slot: int, car_id: int) -> None:
        self.send(slot, bytes([ACSP_GET_CAR_INFO, car_id]))

    def car_count(self, slot: int) -> int:
        return max_cars_for_slot(self.state, slot)

    def ask_all_cars(self, slot: int) -> None:
        for car_id in range(self.car_count(slot)):
            self.ask_car(slot, car_id)

    def ask_session(self, slot: int) -> None:
        self.send(slot, bytes([ACSP_GET_SESSION_INFO, 255]))

    def remember(self, slot: int, info: dict) -> None:
        if not info.get("guid"):
            return
        self.cars.setdefault(slot, {})[int(info["car_id"])] = {
            "guid": info["guid"],
            "name": info.get("name") or info["guid"],
            "car": info.get("car") or "",
        }
        self.publish_online(slot)

    def forget(self, slot: int, car_id: int) -> None:
        self.cars.get(slot, {}).pop(car_id, None)
        self.publish_online(slot)

    def publish_online(self, slot: int) -> None:
        lobby_id = self.lobby_id(slot)
        if lobby_id.startswith("slot-") and not self.cars.get(slot):
            return
        meta = lobby_meta(lobby_id, self.statics)
        self.board.set_online(
            lobby_id,
            list(self.cars.get(slot, {}).values()),
            name=meta.get("name") or lobby_id,
            track=meta.get("track") or "",
        )

    def lobby_id(self, slot: int) -> str:
        return slot_to_lobby_id(slot, self.statics, self.races, state=self.state)

    def handle(self, slot: int, data: bytes) -> None:
        if not data:
            return
        kind = data[0]
        payload = data[1:]
        lobby_id = self.lobby_id(slot)
        meta = lobby_meta(lobby_id, self.statics)

        if kind == ACSP_VERSION:
            print(f"plugin slot {slot} protocol {payload[0] if payload else '?'}")
            self.ask_session(slot)
            self.ask_all_cars(slot)
        elif kind in (ACSP_NEW_SESSION, ACSP_SESSION_INFO):
            info: dict = {}
            try:
                info = parse_session_info(payload)
            except ValueError:
                pass
            if kind == ACSP_NEW_SESSION:
                self.board.reset_session(
                    lobby_id,
                    name=meta.get("name") or info.get("server_name") or lobby_id,
                    track=meta.get("track") or "",
                )
                print(f"plugin slot {slot} new session {info.get('name') or ''}")
            self.ask_all_cars(slot)
        elif kind == ACSP_NEW_CONNECTION:
            info = parse_new_connection(payload)
            self.remember(slot, info)
            print(f"plugin slot {slot} join {info['name']} {info['guid']} car={info['car']}")
        elif kind == ACSP_CONNECTION_CLOSED:
            info = parse_connection_closed(payload)
            self.forget(slot, int(info["car_id"]))
        elif kind == ACSP_CAR_INFO:
            info = parse_car_info(payload)
            if info["connected"] and info["guid"]:
                self.remember(slot, info)
            elif not info["connected"]:
                self.forget(slot, int(info["car_id"]))
        elif kind == ACSP_CLIENT_LOADED:
            if payload:
                self.ask_car(slot, payload[0])
        elif kind == ACSP_LAP_COMPLETED:
            car_id, laptime, cuts = parse_lap_completed(payload)
            driver = self.cars.get(slot, {}).get(car_id)
            if not driver:
                self.ask_car(slot, car_id)
                print(f"plugin slot {slot} lap car={car_id} unknown driver cuts={cuts} ms={laptime}")
                return
            pb = self.board.record(
                lobby_id,
                guid=driver["guid"],
                name=driver["name"],
                car=driver["car"],
                ms=laptime,
                cuts=cuts,
            )
            meta = series_quali_meta(self.state, slot)
            if meta and cuts == 0 and valid_lap(laptime, cuts, driver["guid"]):
                try:
                    sync_series_quali_lap(
                        self.state,
                        str(meta["series_id"]),
                        str(meta["round_id"]),
                        steam_id=driver["guid"],
                        lap_ms=laptime,
                    )
                except Exception as exc:
                    print(f"plugin series quali sync failed: {exc}")
            print(
                f"plugin slot {slot} lap {driver['name']} {driver['guid']} "
                f"{driver['car']} {laptime}ms cuts={cuts} pb={pb}"
            )
        elif kind == ACSP_END_SESSION:
            pass

    def serve(self) -> None:
        self.bind()
        print("plugin waiting for laps")
        idle_ticks = 0
        while True:
            timeout = self.poll_timeout()
            ready, _, _ = select.select(list(self.socks), [], [], timeout)
            try:
                self.tick_heartbeat()
            except Exception:
                traceback.print_exc()
            try:
                self.tick_downtime()
            except Exception:
                traceback.print_exc()
            if ready:
                idle_ticks = 0
            else:
                idle_ticks += 1
                # ~30s between occupancy refreshes even with a 0.2s countdown timeout.
                if idle_ticks * timeout >= 30:
                    idle_ticks = 0
                    for slot in self.slot_sock:
                        self.ask_all_cars(slot)
            for sock in ready:
                slot = self.socks[sock]
                try:
                    data, _addr = sock.recvfrom(4096)
                    self.handle(slot, data)
                except Exception:
                    traceback.print_exc()


def main() -> None:
    state = Path(os.environ.get("AC_STATE", "/data"))
    catalog = Path(os.environ.get("AC_CATALOG", "/catalog"))
    dist = Path(os.environ.get("AC_DIST", str(state / "dist")))
    host = os.environ.get("PLUGIN_HOST", "127.0.0.1")
    plugin = Plugin(state=state, catalog=catalog, dist=dist, host=host)
    plugin.serve()


if __name__ == "__main__":
    main()
