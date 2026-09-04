#!/usr/bin/env python3
"""Prometheus exporter for Dream Router firewall / port-forward hit counters.

UniFi's API does not expose nf_conntrack / NAT table size. The closest
signal for WAN scans and lobby-port bots is firewall_hits_state, especially
WAN_PF_IN (port-forward hits) and WAN_LOCAL (hits aimed at the router).
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

INTERESTING_CHAINS = frozenset(
    {"WAN_IN", "WAN_LOCAL", "WAN_OUT", "WAN_PF_IN", "WAN_PF_OUT"}
)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_password() -> str:
    path = Path(_env("UNIFI_PASS_FILE", "/var/lib/monitoring/secrets/unpoller.pass"))
    return path.read_text(encoding="utf-8").strip()


def prom_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_metrics(hits: list[dict]) -> str:
    lines = [
        "# HELP udr_firewall_packets_total Packets counted by UniFi firewall_hits_state",
        "# TYPE udr_firewall_packets_total counter",
    ]
    for entry in hits:
        chain = str(entry.get("chain") or "")
        if chain not in INTERESTING_CHAINS:
            continue
        rid = str(entry.get("id") or "")
        packets = int(entry.get("packets") or 0)
        lines.append(
            f'udr_firewall_packets_total{{chain="{prom_escape(chain)}",'
            f'rule="{prom_escape(rid)}"}} {packets}'
        )
    lines.append("# HELP udr_fw_exporter_up 1 if the last UniFi poll succeeded")
    lines.append("# TYPE udr_fw_exporter_up gauge")
    return "\n".join(lines) + "\n"


class UnifiClient:
    def __init__(self) -> None:
        self.host = _env("UNIFI_HOST", "https://192.168.1.1").rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"https://{self.host}"
        self.user = _env("UNIFI_USER", "unpoller")
        self.password = load_password()
        self._opener: urllib.request.OpenerDirector | None = None
        self._csrf: str | None = None

    def _ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def login(self) -> None:
        jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ssl_context()),
            urllib.request.HTTPCookieProcessor(jar),
        )
        body = json.dumps({"username": self.user, "password": self.password}).encode()
        req = urllib.request.Request(
            f"{self.host}/api/auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener.open(req, timeout=20) as resp:
            self._csrf = resp.headers.get("X-CSRF-Token") or resp.headers.get("x-csrf-token")
            resp.read()
        if not self._csrf:
            for cookie in jar:
                if cookie.name.upper() in ("CSRF_TOKEN", "X-CSRF-TOKEN"):
                    self._csrf = cookie.value
                    break

    def get(self, path: str) -> Any:
        if self._opener is None:
            self.login()
        assert self._opener is not None
        headers = {"Accept": "application/json"}
        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        req = urllib.request.Request(self.host + path, headers=headers)
        try:
            with self._opener.open(req, timeout=25) as resp:
                parsed = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self.login()
                return self.get(path)
            raise
        if isinstance(parsed, dict) and "data" in parsed:
            return parsed["data"]
        return parsed

    def poll(self) -> list[dict]:
        devices = self.get("/proxy/network/api/s/default/stat/device")
        for item in devices if isinstance(devices, list) else []:
            if item.get("type") != "udm":
                continue
            return list((item.get("firewall_hits_state") or {}).get("entries") or [])
        return []


class Handler(BaseHTTPRequestHandler):
    client: UnifiClient
    cache = "# HELP udr_fw_exporter_up 1 if the last UniFi poll succeeded\n# TYPE udr_fw_exporter_up gauge\nudr_fw_exporter_up 0\n"
    fetched = 0.0

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in ("/metrics", "/"):
            self.send_error(404)
            return
        now = time.time()
        body = Handler.cache
        if now - Handler.fetched > 15:
            try:
                hits = Handler.client.poll()
                body = render_metrics(hits) + "udr_fw_exporter_up 1\n"
                Handler.cache = body
                Handler.fetched = now
            except Exception as exc:
                body = Handler.cache + f"# poll_error {type(exc).__name__}\n"
                if "udr_fw_exporter_up 1" in body:
                    body = body.replace("udr_fw_exporter_up 1\n", "udr_fw_exporter_up 0\n")
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    bind = _env("UDR_FW_BIND", "127.0.0.1:9131")
    host, port_s = bind.rsplit(":", 1)
    Handler.client = UnifiClient()
    server = ThreadingHTTPServer((host, int(port_s)), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
