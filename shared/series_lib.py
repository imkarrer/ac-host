"""Series championship state, standings, and player-page payload."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERIES_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
DEFAULT_SERIES = {
    "qualMode": "live",
    "qualMinutes": 12,
    "raceMinutes": 20,
    "points": [10, 8, 6, 4, 2],
    "fastestLapPoint": 1,
    "dropRounds": 0,
    "tyreCompound": "ST",
    "maxDrivers": 20,
    "rulesUrl": "",
}

ROUND_STATUSES = (
    "scheduled",
    "open",
    "quali",
    "grid_locked",
    "racing",
    "provisional",
    "final",
    "archived",
)

VALID_ROUND_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"open"},
    "open": {"quali", "grid_locked", "racing"},
    "quali": {"grid_locked", "racing"},
    "grid_locked": {"quali", "racing"},
    "racing": {"provisional", "grid_locked"},
    "provisional": {"final", "racing"},
    "final": {"archived"},
    "archived": set(),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def resolve_state_root(path: Path) -> Path:
    """Find the directory that actually holds ``series/``.

    On the box, Docker mounts `/var/lib/ac-host` as `/data`, but signups live
    under `/var/lib/ac-host/state/series`. A caller that passes `/data` (or
    `/var/lib/ac-host`) still has to land on the real tree.
    """
    root = Path(path)
    if (root / "series").is_dir():
        return root
    nested = root / "state"
    if (nested / "series").is_dir():
        return nested
    return root


def series_state_dir(state_root: Path, series_id: str) -> Path:
    return resolve_state_root(state_root) / "series" / series_id


def catalog_series_path(catalog: Path, series_id: str) -> Path:
    return catalog / "series" / f"{series_id}.json"


def spec_path(state_root: Path, series_id: str) -> Path:
    return series_state_dir(state_root, series_id) / "spec.json"


def slug_series_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError("name does not produce a series id")
    return slug[:32]


def validate_series_id(series_id: str) -> str:
    cleaned = str(series_id).strip().lower()
    if not SERIES_ID_RE.match(cleaned):
        raise ValueError(
            f"invalid series id {series_id!r}; use lowercase letters, numbers, hyphens"
        )
    return cleaned


def list_series_ids(catalog: Path, state_root: Path | None = None) -> list[str]:
    ids: set[str] = set()
    root = catalog / "series"
    if root.is_dir():
        ids.update(p.stem for p in root.glob("*.json"))
    if state_root is not None:
        series_root = resolve_state_root(state_root) / "series"
        if series_root.is_dir():
            for path in series_root.iterdir():
                if path.is_dir() and (
                    (path / "spec.json").is_file() or (path / "signups.json").is_file()
                ):
                    ids.add(path.name)
    return sorted(ids)


def list_tracks(catalog: Path) -> list[tuple[str, str]]:
    root = catalog / "tracks"
    if not root.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(root.glob("*.json")):
        data = load_json(path, {})
        tid = str(data.get("id") or path.stem)
        out.append((tid, str(data.get("displayName") or tid)))
    return out


def parse_scheduled(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError as exc:
        raise ValueError(
            f"unrecognized date {value!r}; try 2026-09-12 19:00 or 2026-09-12"
        ) from exc


def load_catalog(catalog: Path, series_id: str, state_root: Path | None = None) -> dict:
    if state_root is not None:
        path = spec_path(state_root, series_id)
        if path.is_file():
            data = load_json(path, {})
            if isinstance(data, dict) and data.get("id"):
                return data
    path = catalog_series_path(catalog, series_id)
    if not path.is_file():
        raise FileNotFoundError(f"unknown series {series_id!r}")
    data = load_json(path, {})
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(f"invalid catalog for {series_id!r}")
    return data


def save_spec(state_root: Path, spec: dict) -> Path:
    series_id = validate_series_id(str(spec.get("id") or ""))
    spec["id"] = series_id
    path = spec_path(state_root, series_id)
    spec["updated_at"] = utcnow()
    save_json(path, spec)
    return path


def next_round_id(spec: dict) -> str:
    used = []
    for rnd in spec.get("rounds") or []:
        rid = str(rnd.get("id") or "")
        if re.fullmatch(r"r\d{2}", rid):
            used.append(int(rid[1:]))
    n = (max(used) + 1) if used else 0
    return f"r{n:02d}"


def create_series(
    state_root: Path,
    catalog: Path,
    *,
    name: str,
    car: str,
    series_id: str = "",
    track: str = "",
    scheduled: str | None = None,
) -> dict:
    """Create a series from Discord (or CLI). Writes spec.json, then state."""
    name = str(name).strip()
    car = str(car).strip()
    if not name:
        raise ValueError("name is required")
    if not car:
        raise ValueError("car is required")
    sid = validate_series_id(series_id or slug_series_id(name))
    if spec_path(state_root, sid).is_file():
        raise ValueError(f"{sid} already exists — use /admin add-round to extend the calendar")

    try:
        spec = dict(load_catalog(catalog, sid))
    except FileNotFoundError:
        spec = {"id": sid, **DEFAULT_SERIES, "rounds": []}

    spec["id"] = sid
    spec["displayName"] = name
    spec["car"] = car
    spec.setdefault("discordRole", sid)
    spec.setdefault("rounds", [])
    if track:
        known = {tid for tid, _ in list_tracks(catalog)}
        if known and track not in known:
            raise ValueError(f"unknown track {track!r}")
    if track and not spec["rounds"]:
        spec["rounds"] = [
            {
                "id": "r00",
                "track": track,
                "scheduled": scheduled,
                "pilot": False,
            }
        ]
    save_spec(state_root, spec)
    init_series_state(state_root, catalog, sid)
    return spec


def add_round(
    state_root: Path,
    catalog: Path,
    series_id: str,
    *,
    track: str,
    scheduled: str | None = None,
    pilot: bool = False,
) -> dict:
    """Append a calendar round. Creates spec.json from the repo catalog if needed."""
    track = str(track).strip()
    if not track:
        raise ValueError("track is required")
    known = {tid for tid, _ in list_tracks(catalog)}
    if known and track not in known:
        raise ValueError(f"unknown track {track!r}")
    try:
        spec = dict(load_catalog(catalog, series_id, state_root))
    except FileNotFoundError:
        raise FileNotFoundError(f"unknown series {series_id!r}; run /admin init first") from None
    rid = next_round_id(spec)
    row = {"id": rid, "track": track, "scheduled": scheduled, "pilot": bool(pilot)}
    spec.setdefault("rounds", []).append(row)
    save_spec(state_root, spec)
    init_series_state(state_root, catalog, series_id)
    return row


def load_track_catalog(catalog: Path, track_id: str) -> dict:
    path = catalog / "tracks" / f"{track_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"unknown track {track_id!r}")
    return load_json(path, {})


def load_car_catalog(catalog: Path, car_id: str) -> dict:
    path = catalog / "cars" / f"{car_id}.json"
    if not path.is_file():
        return {"folder": car_id, "displayName": car_id}
    return load_json(path, {"folder": car_id, "displayName": car_id})


def init_series_state(state_root: Path, catalog: Path, series_id: str) -> dict:
    spec = load_catalog(catalog, series_id, state_root)
    root = series_state_dir(state_root, series_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "rounds").mkdir(parents=True, exist_ok=True)
    signups_path = root / "signups.json"
    if not signups_path.is_file():
        save_json(
            signups_path,
            {
                "series_id": series_id,
                "updated_at": utcnow(),
                "drivers": [],
            },
        )
    meta_path = root / "meta.json"
    if not meta_path.is_file():
        save_json(
            meta_path,
            {
                "series_id": series_id,
                "initialized_at": utcnow(),
                "discord_role": spec.get("discordRole") or series_id,
                "discord_category_active": "",
                "discord_category_archive": "",
            },
        )
    for rnd in spec.get("rounds") or []:
        round_id = str(rnd.get("id") or "")
        if not round_id:
            continue
        round_path = root / "rounds" / f"{round_id}.json"
        if round_path.is_file():
            continue
        save_json(
            round_path,
            {
                "id": round_id,
                "series_id": series_id,
                "track": rnd.get("track"),
                "scheduled": rnd.get("scheduled"),
                "pilot": bool(rnd.get("pilot")),
                "status": "scheduled",
                "discord_channel_id": "",
                "qual_mode": spec.get("qualMode") or "live",
                "grid": [],
                "quali_laps": {},
                "penalties": [],
                "results": None,
                "join_url": "",
                "updated_at": utcnow(),
            },
        )
    return {"root": str(root), "series_id": series_id}


def load_signups(state_root: Path, series_id: str) -> dict:
    path = series_state_dir(state_root, series_id) / "signups.json"
    data = load_json(path, {"series_id": series_id, "drivers": []})
    data.setdefault("drivers", [])
    return data


def save_signups(state_root: Path, series_id: str, data: dict) -> None:
    data["updated_at"] = utcnow()
    save_json(series_state_dir(state_root, series_id) / "signups.json", data)


def find_signup(signups: dict, *, steam_id: str | None = None, discord_id: str | None = None) -> dict | None:
    for driver in signups.get("drivers") or []:
        if steam_id and str(driver.get("steam_id") or "") == steam_id:
            return driver
        if discord_id and str(driver.get("discord_id") or "") == discord_id:
            return driver
    return None


def round_path(state_root: Path, series_id: str, round_id: str) -> Path:
    return series_state_dir(state_root, series_id) / "rounds" / f"{round_id}.json"


def load_round(state_root: Path, series_id: str, round_id: str) -> dict:
    path = round_path(state_root, series_id, round_id)
    if not path.is_file():
        raise FileNotFoundError(f"unknown round {round_id!r} for {series_id!r}")
    return load_json(path, {})


def save_round(state_root: Path, series_id: str, round_id: str, data: dict) -> None:
    data["updated_at"] = utcnow()
    save_json(round_path(state_root, series_id, round_id), data)


def set_round_status(round_data: dict, status: str) -> None:
    if status not in ROUND_STATUSES:
        raise ValueError(f"invalid round status {status!r}")
    current = str(round_data.get("status") or "scheduled")
    allowed = VALID_ROUND_TRANSITIONS.get(current, set())
    if status != current and status not in allowed:
        raise ValueError(f"cannot transition {current!r} → {status!r}")
    round_data["status"] = status


def catalog_round(spec: dict, round_id: str) -> dict:
    for rnd in spec.get("rounds") or []:
        if str(rnd.get("id") or "") == round_id:
            return rnd
    raise KeyError(round_id)


def signup_driver(
    state_root: Path,
    catalog: Path,
    series_id: str,
    *,
    steam_id: str,
    discord_id: str,
    name: str,
    skin: str = "",
    number: str = "",
) -> dict:
    spec = load_catalog(catalog, series_id, state_root)
    signups = load_signups(state_root, series_id)
    existing = find_signup(signups, steam_id=steam_id)
    if existing:
        if skin:
            existing["skin"] = skin
        if number:
            existing["number"] = str(number).strip()
        existing["name"] = name
        existing["discord_id"] = discord_id
        save_signups(state_root, series_id, signups)
        return existing
    car = str(spec.get("car") or "")
    driver = {
        "steam_id": steam_id,
        "discord_id": discord_id,
        "name": name,
        "car": car,
        "skin": skin,
        "number": str(number).strip(),
        "signed_up_at": utcnow(),
    }
    signups.setdefault("drivers", []).append(driver)
    save_signups(state_root, series_id, signups)
    return driver


def withdraw_driver(state_root: Path, series_id: str, *, discord_id: str) -> bool:
    signups = load_signups(state_root, series_id)
    drivers = signups.get("drivers") or []
    kept = [d for d in drivers if str(d.get("discord_id") or "") != discord_id]
    if len(kept) == len(drivers):
        return False
    signups["drivers"] = kept
    save_signups(state_root, series_id, signups)
    return True


def stamp_player_number(state_root: Path, *, steam_id: str, number: str) -> int:
    """Copy a reserved practice number onto every series signup for this Steam ID."""
    number = str(number).strip()
    if not steam_id or not number:
        return 0
    root = resolve_state_root(state_root) / "series"
    if not root.is_dir():
        return 0
    updated = 0
    for path in root.iterdir():
        signups_path = path / "signups.json"
        if not path.is_dir() or not signups_path.is_file():
            continue
        signups = load_json(signups_path, {})
        changed = False
        for driver in signups.get("drivers") or []:
            if str(driver.get("steam_id") or "") == steam_id:
                driver["number"] = number
                changed = True
        if changed:
            save_signups(state_root, path.name, signups)
            updated += 1
    return updated


def grid_from_quali(signups: dict, quali_laps: dict[str, int], *, missed_back: bool = True) -> list[dict]:
    """Sort signups by quali time; drivers without a valid lap go to the back."""
    drivers = list(signups.get("drivers") or [])
    with_time: list[tuple[int, dict]] = []
    without: list[dict] = []
    for driver in drivers:
        sid = str(driver.get("steam_id") or "")
        ms = quali_laps.get(sid)
        if ms is None:
            without.append(driver)
        else:
            with_time.append((int(ms), driver))
    with_time.sort(key=lambda item: item[0])
    ordered = [d for _, d in with_time]
    if missed_back:
        ordered.extend(without)
    grid = []
    for pos, driver in enumerate(ordered, start=1):
        sid = str(driver.get("steam_id") or "")
        grid.append(
            {
                "pos": pos,
                "steam_id": sid,
                "name": driver.get("name") or sid,
                "skin": driver.get("skin") or "",
                "qual_time_ms": quali_laps.get(sid),
            }
        )
    return grid


def quali_lobby_id(series_id: str, round_id: str) -> str:
    return f"series-{series_id}-{round_id}-quali"


def parse_quali_lobby_id(lobby_id: str) -> tuple[str, str] | None:
    prefix = "series-"
    suffix = "-quali"
    if not lobby_id.startswith(prefix) or not lobby_id.endswith(suffix):
        return None
    body = lobby_id[len(prefix) : -len(suffix)]
    if "-r" not in body:
        return None
    series_id, round_id = body.rsplit("-", 1)
    if not series_id.startswith("series-"):
        series_id = f"series-{series_id}" if series_id else ""
    if not round_id.startswith("r"):
        return None
    return series_id, round_id


def series_quali_meta_for_slot(state_root: Path, slot: int) -> dict | None:
    for meta_path in state_root.glob("series/*/rounds/*/quali/meta.json"):
        meta = load_json(meta_path, {})
        if int(meta.get("slot") or -1) == slot:
            return meta
    return None


def record_quali_lap(
    state_root: Path,
    series_id: str,
    round_id: str,
    *,
    steam_id: str,
    lap_ms: int,
) -> bool:
    """Keep best valid quali lap on the round (cuts must be rejected before call)."""
    rnd = load_round(state_root, series_id, round_id)
    laps: dict[str, int] = {}
    for key, value in (rnd.get("quali_laps") or {}).items():
        laps[str(key)] = int(value)
    prev = laps.get(steam_id)
    if prev is not None and int(lap_ms) >= int(prev):
        return False
    laps[steam_id] = int(lap_ms)
    rnd["quali_laps"] = laps
    save_round(state_root, series_id, round_id, rnd)
    return True


def import_quali_laps_from_leaderboard(
    state_root: Path,
    series_id: str,
    round_id: str,
    *,
    car: str,
) -> dict[str, int]:
    """Read official quali PBs from leaderboard.json (plugin rejects cuts)."""
    board = load_json(state_root / "leaderboard.json", {"lobbies": {}})
    lobby = (board.get("lobbies") or {}).get(quali_lobby_id(series_id, round_id)) or {}
    laps: dict[str, int] = {}
    for entry in lobby.get("allTime") or []:
        if car and str(entry.get("car") or "") != car:
            continue
        guid = str(entry.get("guid") or "")
        ms = entry.get("ms")
        if not guid or ms is None:
            continue
        laps[guid] = int(ms)
    return laps


def sync_quali_laps_to_round(
    state_root: Path,
    catalog: Path,
    series_id: str,
    round_id: str,
) -> dict[str, int]:
    """Merge leaderboard quali times into round state (best lap wins)."""
    spec = load_catalog(catalog, series_id, state_root)
    car = str(spec.get("car") or "")
    imported = import_quali_laps_from_leaderboard(state_root, series_id, round_id, car=car)
    rnd = load_round(state_root, series_id, round_id)
    merged: dict[str, int] = {}
    for key, value in (rnd.get("quali_laps") or {}).items():
        merged[str(key)] = int(value)
    for guid, ms in imported.items():
        if guid not in merged or int(ms) < int(merged[guid]):
            merged[guid] = int(ms)
    rnd["quali_laps"] = merged
    save_round(state_root, series_id, round_id, rnd)
    return merged


def lock_grid_from_quali(
    state_root: Path,
    catalog: Path,
    series_id: str,
    round_id: str,
) -> list[dict]:
    """Sort quali laps → grid[] → status grid_locked. Missed quali → back."""
    sync_quali_laps_to_round(state_root, catalog, series_id, round_id)
    signups = load_signups(state_root, series_id)
    rnd = load_round(state_root, series_id, round_id)
    quali = {str(k): int(v) for k, v in (rnd.get("quali_laps") or {}).items()}
    grid = grid_from_quali(signups, quali)
    rnd["grid"] = grid
    set_round_status(rnd, "grid_locked")
    save_round(state_root, series_id, round_id, rnd)
    return grid


def apply_race_points(finishes: list[dict], points_table: list[int], *, fastest_lap_point: int = 0) -> list[dict]:
    out = []
    fastest_sid = None
    if fastest_lap_point:
        best = None
        for row in finishes:
            fl = row.get("best_lap_ms")
            if fl is None:
                continue
            if best is None or int(fl) < best[0]:
                best = (int(fl), str(row.get("steam_id") or ""))
        if best:
            fastest_sid = best[1]
    for row in finishes:
        pos = int(row.get("pos") or 0)
        pts = points_table[pos - 1] if 0 < pos <= len(points_table) else 0
        sid = str(row.get("steam_id") or "")
        if fastest_lap_point and sid == fastest_sid and pts > 0:
            pts += fastest_lap_point
        item = dict(row)
        item["points"] = pts
        item["fastest_lap"] = sid == fastest_sid
        out.append(item)
    return out


def compute_standings(
    spec: dict,
    signups: dict,
    rounds: list[dict],
) -> list[dict]:
    points_table = [int(x) for x in (spec.get("points") or [])]
    drop_rounds = int(spec.get("dropRounds") or 0)
    fastest_lap_point = int(spec.get("fastestLapPoint") or 0)
    by_driver: dict[str, dict] = {}
    for driver in signups.get("drivers") or []:
        sid = str(driver.get("steam_id") or "")
        by_driver[sid] = {
            "guid": sid,
            "name": driver.get("name") or sid,
            "points": 0,
            "rounds": {},
            "wins": 0,
            "podiums": 0,
        }
    final_rounds = [r for r in rounds if str(r.get("status") or "") in ("final", "archived")]
    for rnd in final_rounds:
        rid = str(rnd.get("id") or "")
        results = rnd.get("results") or {}
        finishes = results.get("finishes") or []
        scored = apply_race_points(finishes, points_table, fastest_lap_point=fastest_lap_point)
        for row in scored:
            sid = str(row.get("steam_id") or "")
            if sid not in by_driver:
                by_driver[sid] = {
                    "guid": sid,
                    "name": row.get("name") or sid,
                    "points": 0,
                    "rounds": {},
                    "wins": 0,
                    "podiums": 0,
                }
            pts = int(row.get("points") or 0)
            by_driver[sid]["rounds"][rid] = pts
            if int(row.get("pos") or 0) == 1:
                by_driver[sid]["wins"] += 1
            if int(row.get("pos") or 0) <= 3:
                by_driver[sid]["podiums"] += 1

    standings = []
    for sid, row in by_driver.items():
        round_points = [(rid, pts) for rid, pts in row["rounds"].items()]
        dropped_rid = None
        total = sum(pts for _, pts in round_points)
        if drop_rounds and len(round_points) > drop_rounds:
            worst = sorted(round_points, key=lambda item: item[1])[:drop_rounds]
            dropped_rid = worst[0][0] if worst else None
            total = sum(pts for rid, pts in round_points if rid != dropped_rid)
        standings.append(
            {
                "guid": sid,
                "name": row["name"],
                "points": total,
                "rounds": row["rounds"],
                "droppedRound": dropped_rid,
                "wins": row["wins"],
                "podiums": row["podiums"],
            }
        )
    standings.sort(key=lambda r: (-r["points"], -r["wins"], -r["podiums"], r["name"].lower()))
    for pos, row in enumerate(standings, start=1):
        row["pos"] = pos
    return standings


def load_all_rounds(state_root: Path, series_id: str) -> list[dict]:
    rounds_dir = series_state_dir(state_root, series_id) / "rounds"
    if not rounds_dir.is_dir():
        return []
    rounds = []
    for path in sorted(rounds_dir.glob("*.json")):
        data = load_json(path, {})
        if data:
            rounds.append(data)
    return rounds


def active_round_id(rounds: list[dict]) -> str | None:
    priority = ("racing", "quali", "grid_locked", "open", "provisional", "scheduled")
    for status in priority:
        for rnd in rounds:
            if str(rnd.get("status") or "") == status:
                return str(rnd.get("id") or "")
    for rnd in reversed(rounds):
        if str(rnd.get("status") or "") not in ("final", "archived"):
            return str(rnd.get("id") or "")
    return str(rounds[0].get("id") or "") if rounds else None


def build_page_payload(
    *,
    spec: dict,
    signups: dict,
    rounds: list[dict],
    catalog: Path,
    pages_url: str,
    join_url: str = "",
) -> dict:
    standings = compute_standings(spec, signups, rounds)
    car_id = str(spec.get("car") or "")
    car_meta = load_car_catalog(catalog, car_id)
    out_rounds = []
    for rnd in rounds:
        track_id = str(rnd.get("track") or "")
        track_meta = load_track_catalog(catalog, track_id) if track_id else {}
        item = {
            "id": rnd.get("id"),
            "track": {
                "id": track_id,
                "name": track_meta.get("displayName") or track_id,
            },
            "scheduled": rnd.get("scheduled"),
            "pilot": bool(rnd.get("pilot")),
            "status": rnd.get("status") or "scheduled",
            "qualMode": rnd.get("qual_mode") or spec.get("qualMode") or "live",
            "discordChannelUrl": rnd.get("discord_channel_url") or "",
            "joinUrl": rnd.get("join_url") or (join_url if rnd.get("status") == "racing" else ""),
            "grid": rnd.get("grid") or [],
            "results": rnd.get("results"),
        }
        out_rounds.append(item)
    return {
        "id": spec.get("id"),
        "displayName": spec.get("displayName") or spec.get("id"),
        "updatedAt": utcnow(),
        "rulesUrl": spec.get("rulesUrl") or "",
        "discordRole": spec.get("discordRole") or spec.get("id"),
        "car": {"id": car_id, "name": car_meta.get("displayName") or car_id},
        "pointsSystem": spec.get("points") or [],
        "dropRounds": int(spec.get("dropRounds") or 0),
        "fastestLapPoint": int(spec.get("fastestLapPoint") or 0),
        "standings": standings,
        "rounds": out_rounds,
        "activeRoundId": active_round_id(rounds),
        "signupCount": len(signups.get("drivers") or []),
        "pagesUrl": pages_url.rstrip("/"),
    }


def write_page_payload(state_root: Path, catalog: Path, series_id: str, *, pages_url: str, join_url: str = "") -> Path:
    spec = load_catalog(catalog, series_id, state_root)
    signups = load_signups(state_root, series_id)
    rounds = load_all_rounds(state_root, series_id)
    payload = build_page_payload(
        spec=spec,
        signups=signups,
        rounds=rounds,
        catalog=catalog,
        pages_url=pages_url,
        join_url=join_url,
    )
    out = series_state_dir(state_root, series_id) / "standings.json"
    save_json(out, payload)
    return out
