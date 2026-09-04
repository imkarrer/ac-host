#!/usr/bin/env python3
"""Map cAdvisor cgroup ids to live Docker container names.

cAdvisor 0.56 speaks Docker API 1.24; Docker 29 on ac-box requires 1.40+,
so the name label stays the container hash. This exporter reads the Docker
API and exposes a 1:1 id→name gauge for PromQL joins.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def prom_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def docker_name(names: list[Any] | None) -> str:
    if not names:
        return ""
    raw = str(names[0] or "")
    return raw[1:] if raw.startswith("/") else raw


def cadvisor_id(container_id: str) -> str:
    return f"/system.slice/docker-{container_id}.scope"


def render_metrics(containers: list[dict]) -> str:
    lines = [
        "# HELP docker_container_info Always 1; maps cAdvisor id to Docker name",
        "# TYPE docker_container_info gauge",
    ]
    for item in containers:
        cid = str(item.get("Id") or "")
        name = docker_name(item.get("Names"))
        if not cid or not name:
            continue
        lines.append(
            f'docker_container_info{{id="{prom_escape(cadvisor_id(cid))}",'
            f'container="{prom_escape(name)}"}} 1'
        )
    lines.append("# HELP docker_name_exporter_up 1 if the last Docker poll succeeded")
    lines.append("# TYPE docker_name_exporter_up gauge")
    return "\n".join(lines) + "\n"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 10) -> None:
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def list_containers(sock: str | None = None) -> list[dict]:
    path = sock or _env("DOCKER_SOCK", "/run/docker.sock")
    api = _env("DOCKER_API_VERSION", "1.44")
    conn = UnixHTTPConnection(path, timeout=15)
    try:
        conn.request("GET", f"/v{api}/containers/json")
        resp = conn.getresponse()
        body = resp.read().decode()
        if resp.status != 200:
            raise RuntimeError(f"docker {resp.status}: {body[:200]}")
        data = json.loads(body)
    finally:
        conn.close()
    return data if isinstance(data, list) else []


class Handler(BaseHTTPRequestHandler):
    cache = (
        "# HELP docker_name_exporter_up 1 if the last Docker poll succeeded\n"
        "# TYPE docker_name_exporter_up gauge\n"
        "docker_name_exporter_up 0\n"
    )
    fetched = 0.0

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in ("/metrics", "/"):
            self.send_error(404)
            return
        now = time.time()
        body = Handler.cache
        if now - Handler.fetched > 10:
            try:
                body = render_metrics(list_containers()) + "docker_name_exporter_up 1\n"
                Handler.cache = body
                Handler.fetched = now
            except Exception as exc:
                body = Handler.cache
                if "docker_name_exporter_up 1" in body:
                    body = body.replace(
                        "docker_name_exporter_up 1\n", "docker_name_exporter_up 0\n"
                    )
                body += f"# poll_error {type(exc).__name__}\n"
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    bind = _env("DOCKER_NAME_BIND", "127.0.0.1:9132")
    host, port_s = bind.rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port_s)), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
