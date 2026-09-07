#!/usr/bin/env python3
"""Render series quali / race cfg from catalog + round state."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import series_lib  # noqa: E402
from render_cfg import render_series_instance  # noqa: E402

CM_DETAILS_MARK = "\u2139"


def series_container_name(series_id: str, round_id: str, phase: str) -> str:
    return f"ac-series-{series_id}-{round_id}-{phase}"


def series_instance_dir(state: Path, series_id: str, round_id: str, phase: str) -> Path:
    return state / "series" / series_id / "rounds" / round_id / phase


def load_drivers_for_phase(
    *,
    state: Path,
    catalog: Path,
    series_id: str,
    round_id: str,
    phase: str,
) -> list[dict]:
    spec = series_lib.load_catalog(catalog, series_id, state)
    car = str(spec.get("car") or "")
    signups = series_lib.load_signups(state, series_id)
    rnd = series_lib.load_round(state, series_id, round_id)
    grid = rnd.get("grid") or []

    if phase == "race" and grid:
        by_steam = {str(d.get("steam_id") or ""): d for d in signups.get("drivers") or []}
        drivers = []
        for row in sorted(grid, key=lambda r: int(r.get("pos") or 999)):
            sid = str(row.get("steam_id") or "")
            signup = by_steam.get(sid) or {}
            # The numbered livery is built once at signup close, so the signup row
            # is where it lives; a round with no pack falls back to the colour.
            skin = (
                str(row.get("race_skin") or "")
                or str(signup.get("race_skin") or "")
                or str(row.get("skin") or "")
            )
            drivers.append(
                {
                    "steam_id": sid,
                    "skin": skin,
                    "name": str(row.get("name") or ""),
                    "car": car,
                }
            )
        return [d for d in drivers if d["steam_id"]]

    drivers = []
    for driver in signups.get("drivers") or []:
        sid = str(driver.get("steam_id") or "")
        if not sid:
            continue
        drivers.append(
            {
                "steam_id": sid,
                "skin": str(driver.get("skin") or ""),
                "name": str(driver.get("name") or driver.get("discord_name") or sid),
                "car": car,
            }
        )
    return drivers


def render_series(
    *,
    state: Path,
    catalog: Path,
    series_id: str,
    round_id: str,
    phase: str,
    mode: str,
    slot: int,
    udp: int,
    http: int,
    details: int,
    auth_bind: str,
    content: Path,
    admin_password: str,
) -> Path:
    spec = series_lib.load_catalog(catalog, series_id, state)
    rnd_spec = series_lib.catalog_round(spec, round_id)
    track_id = str(rnd_spec.get("track") or "")
    track = series_lib.load_track_catalog(catalog, track_id)
    car = str(spec.get("car") or "")
    max_clients = int(spec.get("maxDrivers") or track.get("maxClients") or 20)

    drivers = load_drivers_for_phase(
        state=state,
        catalog=catalog,
        series_id=series_id,
        round_id=round_id,
        phase=phase,
    )
    if not drivers:
        raise SystemExit(f"no signed-up drivers for {series_id}/{round_id}")

    inst = series_instance_dir(state, series_id, round_id, phase)
    cfg_dir = inst / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (inst / "results").mkdir(parents=True, exist_ok=True)

    display = str(spec.get("displayName") or series_id)
    phase_label = "Quali" if phase == "quali" else "Race"
    server_name = f"{display} {round_id.upper()} {phase_label}{CM_DETAILS_MARK}{details}"

    render_series_instance(
        out=cfg_dir,
        name=server_name,
        track=track,
        car=car,
        mode=mode,
        drivers=drivers,
        max_clients=max_clients,
        udp=udp,
        http=http,
        auth=auth_bind,
        admin_password=admin_password,
        content=content,
        qual_minutes=int(spec.get("qualMinutes") or 12),
        race_minutes=int(spec.get("raceMinutes") or 20),
        legal_tyres=str(spec.get("tyreCompound") or track.get("legalTyres") or "ST"),
    )

    meta = {
        "series_id": series_id,
        "round_id": round_id,
        "phase": phase,
        "mode": mode,
        "track": track_id,
        "car": car,
        "slot": slot,
        "udp": udp,
        "http": http,
        "details": details,
        "drivers": len(drivers),
    }
    (inst / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return cfg_dir


def write_series_env(
    *,
    path: Path,
    series_id: str,
    round_id: str,
    phase: str,
    mode: str,
    slot: int,
    udp: int,
    http: int,
    track: str,
    cfg_dir: Path,
    results_dir: Path,
) -> None:
    lines = [
        f"SERIES_CONTAINER_NAME={series_container_name(series_id, round_id, phase)}",
        f"SERIES_CFG_DIR={cfg_dir}",
        f"SERIES_RESULTS_DIR={results_dir}",
        f"SERIES_ID={series_id}",
        f"SERIES_ROUND_ID={round_id}",
        f"SERIES_PHASE={phase}",
        f"SERIES_MODE={mode}",
        f"SERIES_SLOT={slot}",
        f"SERIES_UDP={udp}",
        f"SERIES_HTTP={http}",
        f"SERIES_TRACK={track}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
