#!/usr/bin/env python3
"""Start/stop static practice lobbies and race containers via docker compose."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "compose" / "docker-compose.yml"
CATALOG = REPO / "catalog"
GAME_START = 9600
HTTP_START = 8081
DETAILS_START = 8181
SLOT_COUNT = 16
CM_DETAILS_MARK = "\u2139"  # ℹ — CM reads the port after this for /api/details

# Reserved for ac-host-dev static lobbies; prod races must not take these slots.
DEV_RESERVED_SLOTS = {8, 9, 10, 11}

ENV_PROFILES: dict[str, dict[str, str]] = {
    "prod": {
        "state": "/var/lib/ac-host",
        "content": "/var/lib/ac-host/content",
        "compose_project": "ac-host",
        "statics": "statics.json",
        "auth_bind": "127.0.0.1:18080",
        "env_file": "compose/env.example",
    },
    "dev": {
        "state": "/var/lib/ac-host-dev",
        "content": "/var/lib/ac-host/content",
        "compose_project": "ac-host-dev",
        "statics": "statics-dev.json",
        "auth_bind": "127.0.0.1:18081",
        "env_file": "compose/env.dev.example",
    },
}

# Mutable after apply_env(); used by all commands.
AC_ENV = "prod"
STATE = Path(os.environ.get("AC_STATE", REPO / "state"))
STATICS_PATH = CATALOG / "statics.json"
SLOTS_PATH = STATE / "slots.json"
COMPOSE_PROJECT = "ac-host"
AUTH_BIND = "127.0.0.1:18080"


def apply_env(name: str) -> None:
    """Select prod or dev paths, compose project, and catalog statics file."""
    global AC_ENV, STATE, STATICS_PATH, SLOTS_PATH, COMPOSE_PROJECT, AUTH_BIND
    if name not in ENV_PROFILES:
        raise SystemExit(f"unknown env {name!r}; use prod or dev")
    AC_ENV = name
    profile = ENV_PROFILES[name]
    STATE = Path(os.environ.get("AC_STATE", profile["state"]))
    if not os.environ.get("AC_STATE"):
        if name == "prod" and not Path(profile["state"]).exists() and (REPO / "state").is_dir():
            STATE = REPO / "state"
        elif name == "dev" and not Path(profile["state"]).exists():
            STATE = REPO / "state-dev"
    STATICS_PATH = CATALOG / profile["statics"]
    SLOTS_PATH = STATE / "slots.json"
    COMPOSE_PROJECT = profile["compose_project"]
    AUTH_BIND = profile["auth_bind"]
    os.environ.setdefault("AC_STATE", str(STATE))
    os.environ.setdefault("AC_CONTENT", profile["content"])
    os.environ.setdefault("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT)
    os.environ.setdefault("AC_CATALOG_STATICS", profile["statics"])
    load_dotenv(env_file_path())


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=True, **kwargs)


def compose_cmd() -> list[str]:
    override = os.environ.get("DOCKER_COMPOSE")
    if override:
        return override.split()
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


def env_file_path() -> Path | None:
    profile = ENV_PROFILES[AC_ENV]
    for candidate in (
        STATE / ".env",
        REPO / profile["env_file"],
        REPO / "compose" / ".env",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_dotenv(path: Path | None) -> None:
    """Apply key=value pairs from an env file (does not override existing os.environ)."""
    if path is None or not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def compose(*args: str) -> None:
    env = os.environ.copy()
    env.setdefault("AC_STATE", str(STATE))
    env.setdefault("AC_CONTENT", str(content_dir()))
    env.setdefault("COMPOSE_PROJECT_NAME", COMPOSE_PROJECT)
    env.setdefault("AC_CATALOG_STATICS", ENV_PROFILES[AC_ENV]["statics"])
    cmd = compose_cmd() + ["-f", str(COMPOSE)]
    env_path = env_file_path()
    if env_path is not None:
        cmd.extend(["--env-file", str(env_path)])
    run(cmd + list(args), env=env, cwd=str(REPO))


def load_statics() -> list[dict]:
    data = json.loads(STATICS_PATH.read_text(encoding="utf-8"))
    lobbies = data["lobbies"]
    slots = [int(item["slot"]) for item in lobbies]
    ids = [item["id"] for item in lobbies]
    if len(slots) != len(set(slots)):
        raise SystemExit(f"duplicate static slots in {STATICS_PATH}")
    if len(ids) != len(set(ids)):
        raise SystemExit(f"duplicate static ids in {STATICS_PATH}")
    return sorted(lobbies, key=lambda item: int(item["slot"]))


def reserved_slots() -> set[int]:
    reserved = {int(item["slot"]) for item in load_statics()}
    if AC_ENV == "prod":
        reserved |= DEV_RESERVED_SLOTS
    return reserved


def ports_for_slot(slot: int) -> tuple[int, int, int]:
    return GAME_START + slot, HTTP_START + slot, DETAILS_START + slot


def unifi_open_slot(slot: int) -> None:
    udp, http, details = ports_for_slot(slot)
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        import unifi_pf

        unifi_pf.open_slot(AC_ENV, slot, udp, http, details)
    except Exception as exc:
        print(f"unifi open slot {slot} skipped: {exc}", file=sys.stderr)


def unifi_close_slot(slot: int) -> None:
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        import unifi_pf

        unifi_pf.close_slot(AC_ENV, slot)
    except Exception as exc:
        print(f"unifi close slot {slot} skipped: {exc}", file=sys.stderr)


def load_slots() -> dict:
    if SLOTS_PATH.is_file():
        return json.loads(SLOTS_PATH.read_text(encoding="utf-8"))
    return {}


def save_slots(slots: dict) -> None:
    SLOTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SLOTS_PATH.write_text(json.dumps(slots, indent=2) + "\n", encoding="utf-8")


def next_free_slot(slots: dict) -> int:
    used = {int(info["slot"]) for info in slots.values()} | reserved_slots()
    for i in range(SLOT_COUNT):
        if i not in used:
            return i
    raise SystemExit(f"no free race slots ({GAME_START}–{GAME_START + SLOT_COUNT - 1} are all in use)")


def render(track: str, mode: str, name: str, udp: int, http: int, out: Path) -> None:
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "render_cfg.py"),
        "--catalog",
        str(CATALOG),
        "--track",
        track,
        "--mode",
        mode,
        "--name",
        name,
        "--udp",
        str(udp),
        "--tcp",
        str(udp),
        "--http",
        str(http),
        "--auth",
        AUTH_BIND,
        "--out",
        str(out),
        "--content",
        str(content_dir()),
        "--whitelist",
        str(STATE / "whitelist.json"),
    ]
    skin_mode = os.environ.get("RENDER_SKIN_MODE")
    if skin_mode:
        cmd.extend(["--skin-mode", skin_mode])
    run(cmd)


def dist_dir() -> Path:
    return STATE / "dist"


def sync_site_content() -> None:
    """Write cars + practice tracks into state/dist for the CM details sidecar.

    Prefer the 124 version already in dist/content.json (from publish_124), then
    ui_car.json on the content tree. Never hardcode an old 124 version.
    """
    dest = dist_dir()
    dest.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO / "scripts"))
    import settings
    from content_manifest import existing_car_version, write_content_json

    version = existing_car_version(dest / "content.json")
    if not version:
        ui_car = content_dir() / "cars" / "abarth_124_2016" / "ui" / "ui_car.json"
        if ui_car.is_file():
            try:
                version = str(json.loads(ui_car.read_text(encoding="utf-8")).get("version") or "").strip()
            except json.JSONDecodeError:
                version = None
    version = version or "2.2"

    write_content_json(
        dest / "content.json",
        settings.github_owner(),
        settings.github_pages_repo(),
        car_version=version,
        car_url=settings.release_124_url(),
    )
    print(f"sync_site_content version={version} -> {dest / 'content.json'}")


def content_dir() -> Path:
    """Prefer a tree that actually has cars/, not an empty gitignored src/content."""
    specified = Path(os.environ.get("AC_CONTENT", REPO / "content"))
    candidates = [specified, Path("/var/lib/ac-host/content"), REPO.parent / "content", REPO / "content"]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        cars = path / "cars"
        if cars.is_dir() and any(cars.iterdir()):
            return path
    return specified


def docker_volume(name: str) -> str:
    """Named volume for the game container.

    Always use the prod compose project for ac-server / steam — those volumes
    hold the one-time Steam-login install of AppID 302550. A fresh
    ac-host-dev_* volume would crash-loop on anonymous steamcmd.
    """
    return f"ac-host_{name}"


def ensure_image() -> None:
    compose("--profile", "build", "build", "static")


def run_server_container(*, name: str, cfg: Path, results: Path) -> None:
    results.mkdir(parents=True, exist_ok=True)
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "host",
            "--restart",
            "unless-stopped",
            "-e",
            "STEAMCMD_LOGIN=anonymous",
            "-e",
            "AC_CFG_DIR=/cfg",
            "-e",
            "AC_CONTENT=/content",
            "-e",
            "AC_RESULTS_DIR=/results",
            "-v",
            f"{docker_volume('ac-server')}:/opt/ac",
            "-v",
            f"{docker_volume('steam')}:/home/ac/Steam",
            "-v",
            f"{content_dir()}:/content:ro",
            "-v",
            f"{cfg}:/cfg:ro",
            "-v",
            f"{results}:/results",
            "ac-host-server:latest",
        ]
    )


def static_container(lobby_id: str) -> str:
    prefix = "ac-dev-static" if AC_ENV == "dev" else "ac-static"
    return f"{prefix}-{lobby_id}"


def selected_statics(only: str | None) -> list[dict]:
    lobbies = load_statics()
    if not only:
        return lobbies
    match = [item for item in lobbies if item["id"] == only]
    if not match:
        known = ", ".join(item["id"] for item in lobbies)
        raise SystemExit(f"unknown static lobby {only!r}; have: {known}")
    return match


def cmd_recycle_static(args: argparse.Namespace) -> None:
    """Re-render cfg and recreate practice containers. Does not rebuild sidecars."""
    for lobby in selected_statics(args.only):
        udp, http, details = ports_for_slot(int(lobby["slot"]))
        cfg = STATE / "static" / lobby["id"] / "cfg"
        results = STATE / "static" / lobby["id"] / "results"
        render(
            lobby["track"],
            "practice",
            f"{lobby['name']}{CM_DETAILS_MARK}{details}",
            udp,
            http,
            cfg,
        )
        run_server_container(name=static_container(lobby["id"]), cfg=cfg, results=results)
        print(
            f"recycled {lobby['id']} on {udp}/{http} details={details} "
            f"track={lobby['track']} env={AC_ENV}"
        )


def cmd_up_static(args: argparse.Namespace) -> None:
    sync_site_content()
    compose("up", "-d", "--build", "auth")
    try:
        compose("up", "-d", "--build", "plugin")
    except subprocess.CalledProcessError:
        print("leaderboard plugin skipped (compose has no plugin service?)", file=sys.stderr)
    ensure_image()
    for lobby in selected_statics(args.only):
        udp, http, details = ports_for_slot(int(lobby["slot"]))
        cfg = STATE / "static" / lobby["id"] / "cfg"
        results = STATE / "static" / lobby["id"] / "results"
        render(
            lobby["track"],
            "practice",
            f"{lobby['name']}{CM_DETAILS_MARK}{details}",
            udp,
            http,
            cfg,
        )
        run_server_container(name=static_container(lobby["id"]), cfg=cfg, results=results)
        unifi_open_slot(int(lobby["slot"]))
        print(
            f"static {lobby['id']} on {udp}/{http} details={details} "
            f"track={lobby['track']} env={AC_ENV}"
        )
    compose("up", "-d", "--build", "details")
    content_path = dist_dir() / "content.json"
    if content_path.is_file():
        print(f"cm content: {content_path}")
    else:
        print("warning: state/dist/content.json missing", file=sys.stderr)


def cmd_down_static(args: argparse.Namespace) -> None:
    for lobby in selected_statics(args.only):
        subprocess.run(["docker", "rm", "-f", static_container(lobby["id"])], check=False)
        unifi_close_slot(int(lobby["slot"]))
    compose("stop", "details")
    if args.auth:
        compose("stop", "auth")
    if args.all:
        compose("stop", "plugin")


def cmd_start_race(args: argparse.Namespace) -> None:
    slots = load_slots()
    if args.name in slots:
        raise SystemExit(f"race {args.name!r} is already running on slot {slots[args.name]['slot']}")
    if args.slot is not None and args.slot in reserved_slots():
        raise SystemExit(f"slot {args.slot} is reserved for a static lobby")
    slot = args.slot if args.slot is not None else next_free_slot(slots)
    udp, http, details = ports_for_slot(slot)
    out = STATE / "races" / args.name / "cfg"
    results = STATE / "races" / args.name / "results"
    render(args.track, "race", f"{args.name}{CM_DETAILS_MARK}{details}", udp, http, out)
    ensure_image()
    run_server_container(name=f"ac-race-{args.name}", cfg=out, results=results)
    unifi_open_slot(slot)
    slots[args.name] = {"slot": slot, "udp": udp, "http": http, "track": args.track}
    save_slots(slots)
    print(f"race {args.name} on {udp}/{http} track={args.track}")


def cmd_stop_race(args: argparse.Namespace) -> None:
    run(["docker", "rm", "-f", f"ac-race-{args.name}"])
    slots = load_slots()
    info = slots.pop(args.name, None)
    save_slots(slots)
    if info is not None:
        unifi_close_slot(int(info["slot"]))


def cmd_status(_: argparse.Namespace) -> None:
    print(f"env={AC_ENV} state={STATE} compose={COMPOSE_PROJECT}")
    compose("ps")
    for lobby in load_statics():
        udp, http, details = ports_for_slot(int(lobby["slot"]))
        print(f"static {lobby['id']}: slot {lobby['slot']}  {udp}/{http} details={details}  {lobby['track']}")
    slots = load_slots()
    if not slots:
        print("no race slots in use")
        return
    for name, info in slots.items():
        print(f"race {name}: slot {info['slot']}  {info['udp']}/{info['http']}  {info['track']}")


def cmd_restart_plugin(_: argparse.Namespace) -> None:
    """Rebuild and restart only the leaderboard plugin (does not kick drivers)."""
    compose("up", "-d", "--build", "plugin")
    print(f"plugin restarted env={AC_ENV}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env",
        choices=("prod", "dev"),
        default=os.environ.get("AC_ENV", "prod"),
        help="prod (default) or dev isolated stack",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up-static", help="Render cfg and start auth + all static practice lobbies")
    up.add_argument("--only", default=None, help="Start one static lobby id")
    up.set_defaults(func=cmd_up_static)

    down = sub.add_parser("down-static")
    down.add_argument("--only", default=None)
    down.add_argument("--auth", action="store_true", help="Also stop the shared auth sidecar")
    down.add_argument("--all", action="store_true", help="Also stop the plugin sidecar")
    down.set_defaults(func=cmd_down_static)

    start = sub.add_parser("start-race", help="Start a race container on the next free port")
    start.add_argument("--name", required=True)
    start.add_argument("--track", default="magione")
    start.add_argument("--slot", type=int, default=None)
    start.set_defaults(func=cmd_start_race)

    stop = sub.add_parser("stop-race")
    stop.add_argument("name")
    stop.set_defaults(func=cmd_stop_race)

    st = sub.add_parser("status")
    st.set_defaults(func=cmd_status)

    rp = sub.add_parser("restart-plugin", help="Restart leaderboard plugin only (no lobby kick)")
    rp.set_defaults(func=cmd_restart_plugin)

    recycle = sub.add_parser(
        "recycle-static",
        help="Nightly: re-render practice cfg and recreate lobby containers (kicks drivers)",
    )
    recycle.add_argument("--only", default=None, help="Recycle one static lobby id")
    recycle.set_defaults(func=cmd_recycle_static)

    args = parser.parse_args()
    apply_env(args.env)
    args.func(args)


if __name__ == "__main__":
    main()
