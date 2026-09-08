#!/usr/bin/env python3
"""Shared settings from environment / .env (no personal defaults in code)."""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.is_file():
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


def load_env_files() -> None:
    state = os.environ.get("AC_STATE", "").strip()
    candidates = []
    if state:
        candidates.append(Path(state) / ".env")
    candidates.extend(
        [
            REPO / ".env",
            REPO / "compose" / ".env",
            REPO / "compose" / "env.example",
        ]
    )
    for path in candidates:
        # Never treat env.example as live config if a real .env exists later in the list —
        # only load example last as soft defaults when nothing else set keys.
        if path.name == "env.example":
            continue
        load_dotenv(path)


load_env_files()


def getenv(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def public_ip() -> str:
    return getenv("AC_PUBLIC_IP", "127.0.0.1")


def box_host() -> str:
    return getenv("AC_BOX_HOST", "127.0.0.1")


def box_user() -> str:
    return getenv("AC_BOX_USER", "nixosuser")


def github_owner() -> str:
    return getenv("AC_GITHUB_OWNER", "OWNER")


def github_pages_repo() -> str:
    return getenv("AC_GITHUB_REPO", "ac-practice")


def github_status_repo() -> str:
    return getenv("GITHUB_STATUS_REPO") or f"{github_owner()}/{github_pages_repo()}"


def status_event_sse(*, dev: bool = False) -> str:
    """Browser EventSource URL. Plugin POSTs to the matching ntfy topic after each JSON push.

    dev=True must track push_status.event_url, which suffixes the topic for the
    dev environment. If the two disagree the dev page subscribes to prod and
    reports prod's health as its own -- an explicit override still wins, since
    an operator pointing both ends somewhere is pointing them at one place.
    """
    explicit = getenv("STATUS_EVENT_SSE")
    if explicit:
        return explicit
    topic = getenv("STATUS_EVENT_URL")
    if topic.endswith("/sse"):
        return topic
    if topic:
        return topic.rstrip("/") + "/sse"
    repo = github_status_repo()
    owner, _, name = repo.partition("/")
    if not owner or not name or owner == "OWNER":
        return ""
    suffix = "-dev" if dev else ""
    return f"https://ntfy.sh/ac-{owner}-{name}-status{suffix}/sse"


def pages_url(*, dev: bool = False) -> str:
    explicit = getenv("AC_PAGES_URL") or getenv("AC_CONTENT_URL")
    if explicit:
        base = explicit.rstrip("/") + "/"
    else:
        base = f"https://{github_owner()}.github.io/{github_pages_repo()}/"
    if dev and not base.rstrip("/").endswith("/dev"):
        return base.rstrip("/") + "/dev/"
    return base


def release_124_url() -> str:
    return (
        getenv("AC_124_RELEASE_URL")
        or f"https://github.com/{github_owner()}/{github_pages_repo()}/releases/download/content/abarth_124_2016.zip"
    )


def release_124_dev_url() -> str:
    """Dev-only 124 zip, so dev can test car changes without touching prod's asset.

    On the box the dev stack sets AC_124_RELEASE_URL in /var/lib/ac-host-dev/.env and
    that is enough, because settings reads $AC_STATE/.env first. Rendering the site
    covers both environments in one process, so the dev page needs its own key.
    """
    return getenv("AC_124_DEV_RELEASE_URL") or release_124_url()


def release_car_url(folder: str) -> str:
    if folder == "abarth_124_2016":
        return release_124_url()
    return (
        f"https://github.com/{github_owner()}/{github_pages_repo()}/releases/download/content/{folder}.zip"
    )


def release_track_url(folder: str) -> str:
    return (
        f"https://github.com/{github_owner()}/{github_pages_repo()}/releases/download/content/{folder}.zip"
    )


def unifi_host() -> str:
    return getenv("UNIFI_HOST", "192.168.1.1")


def unifi_fwd_ip() -> str:
    return getenv("UNIFI_FWD_IP") or box_host()


def join_url(http_port: int) -> str:
    return f"https://acstuff.ru/s/q:race/online/join?ip={public_ip()}&httpPort={http_port}"


def discord_invite_url() -> str:
    """Never-expire discord.gg invite (max_age=0). Created by setup_discord.py."""
    return getenv("DISCORD_INVITE_URL", "https://discord.gg/Rh7vevrUYy")


def discord_channel_url() -> str:
    """Deep link to the Discord channel where /steam-request is used."""
    return getenv(
        "DISCORD_CHANNEL_URL",
        "https://discord.com/channels/1544532113615749210/1545234414265700374",
    )


def discord_feature_requests_url() -> str:
    """Deep link to #feature-requests (car / track asks)."""
    return getenv(
        "DISCORD_FEATURE_REQUESTS_URL",
        "https://discord.com/channels/1544532113615749210/1544893635353649294",
    )
