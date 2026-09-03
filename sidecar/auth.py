#!/usr/bin/env python3
"""HTTP AUTH_PLUGIN for Kunos acServer.

acServer GETs AUTH_PLUGIN_ADDRESS with a guid= SteamID64 query parameter.
Reply body is `0:reason` to allow and `1:reason` to deny.
"""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STEAM64 = re.compile(r"^7656119\d{10}$")


def load_whitelist(path: Path) -> dict:
    if not path.is_file():
        return {"players": []}
    return json.loads(path.read_text(encoding="utf-8"))


def extract_guid(query: dict[str, list[str]]) -> str:
    for key in ("guid", "GUID", "steamid", "steam_id"):
        values = query.get(key) or []
        if values and values[0]:
            return values[0].strip()
    return ""


def decide(
    guid: str,
    whitelist: dict,
    *,
    open_mode: bool,
    required_role: str,
) -> tuple[bool, str]:
    if open_mode:
        return True, "open"
    if not STEAM64.match(guid):
        return False, "invalid steam id"
    for player in whitelist.get("players") or []:
        if str(player.get("steam_id")) != guid:
            continue
        if not player.get("enabled", True):
            return False, "disabled"
        roles = player.get("roles") or []
        if required_role and required_role not in roles:
            return False, f"missing role {required_role}"
        return True, "ok"
    return False, "not on the list"


def format_reply(allowed: bool, reason: str) -> bytes:
    code = "0" if allowed else "1"
    return f"{code}:{reason}\n".encode("utf-8")


class AuthHandler(BaseHTTPRequestHandler):
    server_version = "ac-host-auth/1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/auth", "/health"):
            self.send_error(404)
            return
        if parsed.path == "/health":
            self._write(200, b"ok\n")
            return

        guid = extract_guid(parse_qs(parsed.query))
        whitelist = load_whitelist(self.server.whitelist_path)
        allowed, reason = decide(
            guid,
            whitelist,
            open_mode=self.server.open_mode,
            required_role=self.server.required_role,
        )
        self.log_message("guid=%s allowed=%s reason=%s", guid, allowed, reason)
        self._write(200, format_reply(allowed, reason))

    def _write(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}")


class AuthServer(ThreadingHTTPServer):
    def __init__(self, bind: str, whitelist_path: Path, open_mode: bool, required_role: str):
        host, _, port_s = bind.rpartition(":")
        super().__init__((host or "127.0.0.1", int(port_s)), AuthHandler)
        self.whitelist_path = whitelist_path
        self.open_mode = open_mode
        self.required_role = required_role


def main() -> None:
    bind = os.environ.get("AUTH_BIND", "127.0.0.1:18080")
    whitelist = Path(os.environ.get("WHITELIST_PATH", "/data/whitelist.json"))
    open_mode = os.environ.get("AUTH_OPEN", "0") in {"1", "true", "yes"}
    required_role = os.environ.get("AUTH_REQUIRED_ROLE", "ac-practice")
    if not whitelist.is_file():
        whitelist.parent.mkdir(parents=True, exist_ok=True)
        whitelist.write_text('{"players": []}\n', encoding="utf-8")
    server = AuthServer(bind, whitelist, open_mode, required_role)
    print(f"auth listening on {bind} open={open_mode} role={required_role} list={whitelist}")
    server.serve_forever()


if __name__ == "__main__":
    main()
