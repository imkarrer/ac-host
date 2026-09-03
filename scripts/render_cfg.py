#!/usr/bin/env python3
"""Render server_cfg.ini and entry_list.ini from a catalog track."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Must match sidecar/plugin.py and scripts/acctl.py
GAME_PORT_START = 9600
PLUGIN_LOCAL_START = 11200
PLUGIN_EVENT_START = 11300


def plugin_ports(udp: int) -> tuple[int, int]:
    """acServer command port and sidecar event port for this lobby UDP port."""
    slot = max(0, udp - GAME_PORT_START)
    return PLUGIN_LOCAL_START + slot, PLUGIN_EVENT_START + slot


def load_track(catalog: Path, track_id: str) -> dict:
    path = catalog / "tracks" / f"{track_id}.json"
    if not path.is_file():
        known = sorted(p.stem for p in (catalog / "tracks").glob("*.json"))
        raise SystemExit(f"unknown track {track_id!r}; have: {', '.join(known)}")
    return json.loads(path.read_text(encoding="utf-8"))


# Pickup assigns the first free pit of the requested MODEL. Empty SKIN= becomes
# the car's first folder (00_Rosso). CM "skins for booking" does not change that
# — SUB returns FAILED_PICKUP — so pin a real baked livery here.
PREFERRED_SKIN = {
    "abarth_124_2016": "02_Bianco",
    "tbb_toyota_gr86_premium": "04_trueno_blue",
    "pc_civic": "Championship White",
    "ks_mazda_miata": "02_crystal_white",
    "lotus_elise_sc": "0_racing_green",
    "bmw_m3_e30": "alpine_white",
}


def list_skins(content: Path, car: str) -> list[str]:
    skins = content / "cars" / car / "skins"
    if not skins.is_dir():
        return []
    names = []
    for path in sorted(skins.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if "owner_white" in path.name.lower():
            continue
        if (
            (path / "ui_skin.json").is_file()
            or (path / "preview.jpg").is_file()
            or (path / "skin.ini").is_file()
        ):
            names.append(path.name)
    return names


def skin_for_slot(model: str, index: int, mode: str, content: Path | None) -> str:
    if mode == "empty":
        return ""
    if mode == "cycle" and content is not None:
        skins = list_skins(content, model)
        if skins:
            return skins[index % len(skins)]
        return ""
    return PREFERRED_SKIN.get(model, "")


def entry_list(cars: list[str], slots: int, *, skin_mode: str = "pinned", content: Path | None = None) -> str:
    """Pickup slots: cycle allowed cars; skin assignment depends on skin_mode."""
    if not cars:
        cars = [""]
    blocks = []
    for i in range(slots):
        model = cars[i % len(cars)]
        skin = skin_for_slot(model, i, skin_mode, content)
        blocks.append(
            "\n".join(
                [
                    f"[CAR_{i}]",
                    f"MODEL={model}",
                    f"SKIN={skin}",
                    "SPECTATOR_MODE=0",
                    "DRIVERNAME=",
                    "TEAM=",
                    "GUID=",
                    "BALLAST=0",
                    "RESTRICTOR=0",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def server_cfg(
    *,
    name: str,
    track: dict,
    mode: str,
    udp: int,
    tcp: int,
    http: int,
    auth: str,
    admin_password: str,
    loop: int,
) -> str:
    cars = ";".join(track["cars"])
    auth_line = f"{auth}/?" if auth else ""
    plugin_local, plugin_event = plugin_ports(udp)
    sessions = [
        "[PRACTICE]",
        "NAME=Practice",
        "TIME=1440" if mode == "practice" else "TIME=10",
        "IS_OPEN=1",
        "",
    ]
    if mode == "race":
        sessions.extend(
            [
                "[QUALIFY]",
                "NAME=Qualify",
                "TIME=10",
                "IS_OPEN=1",
                "",
                "[RACE]",
                "NAME=Race",
                "LAPS=8",
                "TIME=0",
                "WAIT_TIME=60",
                "IS_OPEN=1",
                "",
            ]
        )

    return "\n".join(
        [
            "[SERVER]",
            f"NAME={name}",
            f"CARS={cars}",
            f"CONFIG_TRACK={track.get('layout') or ''}",
            f"TRACK={track['folder']}",
            "SUN_ANGLE=48",
            "PASSWORD=",
            f"ADMIN_PASSWORD={admin_password}",
            f"UDP_PORT={udp}",
            f"TCP_PORT={tcp}",
            f"HTTP_PORT={http}",
            "PICKUP_MODE_ENABLED=1",
            f"LOOP_MODE={loop}",
            "SLEEP_TIME=1",
            "CLIENT_SEND_INTERVAL_HZ=18",
            "SEND_BUFFER_SIZE=0",
            "RECV_BUFFER_SIZE=0",
            "RACE_OVER_TIME=180",
            "KICK_QUORUM=85",
            "VOTING_QUORUM=80",
            "VOTE_DURATION=20",
            "BLACKLIST_MODE=1",
            "FUEL_RATE=100",
            "DAMAGE_MULTIPLIER=100",
            "TYRE_WEAR_RATE=100",
            "ALLOWED_TYRES_OUT=2",
            "ABS_ALLOWED=1",
            "TC_ALLOWED=1",
            "STABILITY_ALLOWED=0",
            "AUTOCLUTCH_ALLOWED=0",
            "TYRE_BLANKETS_ALLOWED=0",
            "FORCE_VIRTUAL_MIRROR=1",
            "REGISTER_TO_LOBBY=1",
            f"MAX_CLIENTS={track['maxClients']}",
            f"UDP_PLUGIN_LOCAL_PORT={plugin_local}",
            f"UDP_PLUGIN_ADDRESS=127.0.0.1:{plugin_event}",
            f"AUTH_PLUGIN_ADDRESS={auth_line}",
            f"LEGAL_TYRES={track.get('legalTyres') or 'SV'}",
            "LOCKED_ENTRY_LIST=0",
            "WELCOME_MESSAGE=cfg/welcome.txt",
            "",
            *sessions,
            "[DYNAMIC_TRACK]",
            "SESSION_START=100",
            "RANDOMNESS=0",
            "SESSION_TRANSFER=100",
            "LAP_GAIN=0",
            "",
            "[WEATHER_0]",
            "GRAPHICS=3_clear",
            "BASE_TEMPERATURE_AMBIENT=22",
            "BASE_TEMPERATURE_ROAD=8",
            "VARIATION_AMBIENT=0",
            "VARIATION_ROAD=0",
            "WIND_BASE_SPEED_MIN=0",
            "WIND_BASE_SPEED_MAX=0",
            "WIND_BASE_DIRECTION=0",
            "WIND_VARIATION_DIRECTION=0",
            "",
        ]
    )


def pages_url() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import settings

    return settings.pages_url()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--track", required=True)
    parser.add_argument("--mode", choices=("practice", "race"), default="practice")
    parser.add_argument("--name", required=True)
    parser.add_argument("--udp", type=int, default=9600)
    parser.add_argument("--tcp", type=int, default=9600)
    parser.add_argument("--http", type=int, default=8081)
    parser.add_argument("--auth", default="")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--content",
        type=Path,
        default=None,
        help="Car skins tree for cycle mode; optional for pinned/empty.",
    )
    parser.add_argument(
        "--skin-mode",
        choices=("pinned", "empty", "cycle"),
        default=None,
        help="How to fill SKIN= in entry_list (default: RENDER_SKIN_MODE or pinned).",
    )
    args = parser.parse_args()

    track = load_track(args.catalog, args.track)
    admin = os.environ.get("AC_ADMIN_PASSWORD", "change-me")
    skin_mode = args.skin_mode or os.environ.get("RENDER_SKIN_MODE", "pinned")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "server_cfg.ini").write_text(
        server_cfg(
            name=args.name,
            track=track,
            mode=args.mode,
            udp=args.udp,
            tcp=args.tcp,
            http=args.http,
            auth=args.auth,
            admin_password=admin,
            loop=1 if args.mode == "practice" else 0,
        ),
        encoding="utf-8",
    )
    (args.out / "entry_list.ini").write_text(
        entry_list(track["cars"], int(track["maxClients"]), skin_mode=skin_mode, content=args.content),
        encoding="utf-8",
    )
    (args.out / "welcome.txt").write_text(
        "Install mods from the player page before joining.\n"
        f"Player page: {pages_url()}\n"
        "Content Manager Online can auto-download only the 124 Spider.\n"
        "Install CSP, GR86, Civic, and this track from the page first.\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out / 'server_cfg.ini'}")
    print(f"wrote {args.out / 'entry_list.ini'}")
    print(f"wrote {args.out / 'welcome.txt'}")


if __name__ == "__main__":
    main()
