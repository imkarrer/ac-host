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


def unifi_host() -> str:
    return getenv("UNIFI_HOST", "192.168.1.1")


def unifi_fwd_ip() -> str:
    return getenv("UNIFI_FWD_IP") or box_host()


def join_url(http_port: int) -> str:
    return f"https://acstuff.ru/s/q:race/online/join?ip={public_ip()}&httpPort={http_port}"
