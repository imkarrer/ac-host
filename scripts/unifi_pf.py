#!/usr/bin/env python3
"""Open/close UniFi Dream Router port forwards for ac-host lobby slots.

Uses the classic UniFi OS Network API (cookie login). Disabled unless
UNIFI_PF=1 and UNIFI_USER / UNIFI_PASS are set.

Rule names (stable, idempotent):
  ac-{env}-s{slot}-game   TCP+UDP  game port
  ac-{env}-s{slot}-http   TCP      HTTP_PORT
  ac-{env}-s{slot}-details TCP     details port
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


def enabled() -> bool:
    if os.environ.get("UNIFI_PF", "").strip() not in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("UNIFI_USER") and os.environ.get("UNIFI_PASS"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class UnifiPortForward:
    def __init__(self) -> None:
        self.host = _env("UNIFI_HOST", "192.168.1.1").rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"https://{self.host}"
        self.site = _env("UNIFI_SITE", "default")
        self.user = _env("UNIFI_USER")
        self.password = _env("UNIFI_PASS")
        self.fwd = _env("UNIFI_FWD_IP") or _env("AC_BOX_HOST", "127.0.0.1")
        self.iface = _env("UNIFI_WAN", "wan")
        self._opener: urllib.request.OpenerDirector | None = None
        self._csrf: str | None = None

    def _ssl_context(self) -> ssl.SSLContext:
        # Local console often uses a self-signed cert.
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
            raw = resp.read()
            # UniFi OS often returns CSRF in a header or cookie.
            self._csrf = resp.headers.get("X-CSRF-Token") or resp.headers.get("x-csrf-token")
            if not self._csrf:
                for cookie in jar:
                    if cookie.name.upper() in ("CSRF_TOKEN", "X-CSRF-TOKEN"):
                        self._csrf = cookie.value
                        break
            _ = raw  # body unused; login sets cookies

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        return headers

    def _url(self, path: str) -> str:
        return f"{self.host}/proxy/network/api/s/{self.site}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        if self._opener is None:
            self.login()
        assert self._opener is not None
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(
            self._url(path),
            data=data,
            headers=self._headers(),
            method=method,
        )
        try:
            with self._opener.open(req, timeout=20) as resp:
                text = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"UniFi {method} {path} -> {exc.code}: {detail}") from exc
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "data" in parsed:
            return parsed["data"]
        return parsed

    def list_rules(self) -> list[dict]:
        data = self._request("GET", "rest/portforward")
        if isinstance(data, list):
            return data
        return []

    def ensure_rule(
        self,
        *,
        name: str,
        proto: str,
        port: int,
    ) -> None:
        port_s = str(port)
        existing = {r.get("name"): r for r in self.list_rules() if r.get("name")}
        body = {
            "name": name,
            "enabled": True,
            "proto": proto,
            "src": "any",
            "dst_port": port_s,
            "fwd": self.fwd,
            "fwd_port": port_s,
            "pfwd_interface": self.iface,
            "log": False,
        }
        current = existing.get(name)
        if current:
            rule_id = current.get("_id")
            if (
                current.get("enabled")
                and str(current.get("dst_port")) == port_s
                and current.get("fwd") == self.fwd
                and str(current.get("fwd_port")) == port_s
                and current.get("proto") == proto
            ):
                return
            if not rule_id:
                return
            merged = dict(current)
            merged.update(body)
            self._request("PUT", f"rest/portforward/{rule_id}", merged)
            print(f"unifi updated {name} -> {self.fwd}:{port} {proto}")
            return
        self._request("POST", "rest/portforward", body)
        print(f"unifi opened {name} -> {self.fwd}:{port} {proto}")

    def delete_by_name(self, name: str) -> None:
        for rule in self.list_rules():
            if rule.get("name") != name:
                continue
            rule_id = rule.get("_id")
            if not rule_id:
                continue
            self._request("DELETE", f"rest/portforward/{rule_id}")
            print(f"unifi closed {name}")
            return


def rule_names(env: str, slot: int) -> dict[str, str]:
    prefix = f"ac-{env}-s{slot}"
    return {
        "game": f"{prefix}-game",
        "http": f"{prefix}-http",
        "details": f"{prefix}-details",
    }


def open_slot(env: str, slot: int, udp: int, http: int, details: int) -> None:
    if not enabled():
        return
    client = UnifiPortForward()
    names = rule_names(env, slot)
    client.ensure_rule(name=names["game"], proto="tcp_udp", port=udp)
    client.ensure_rule(name=names["http"], proto="tcp", port=http)
    client.ensure_rule(name=names["details"], proto="tcp", port=details)


def close_slot(env: str, slot: int) -> None:
    if not enabled():
        return
    client = UnifiPortForward()
    for name in rule_names(env, slot).values():
        client.delete_by_name(name)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=os.environ.get("AC_ENV", "prod"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    op = sub.add_parser("open-slot")
    op.add_argument("--slot", type=int, required=True)
    op.add_argument("--udp", type=int, required=True)
    op.add_argument("--http", type=int, required=True)
    op.add_argument("--details", type=int, required=True)
    cl = sub.add_parser("close-slot")
    cl.add_argument("--slot", type=int, required=True)
    ls = sub.add_parser("list")
    args = parser.parse_args()
    if not enabled():
        raise SystemExit("set UNIFI_PF=1 UNIFI_USER=… UNIFI_PASS=… first")
    if args.cmd == "open-slot":
        open_slot(args.env, args.slot, args.udp, args.http, args.details)
    elif args.cmd == "close-slot":
        close_slot(args.env, args.slot)
    elif args.cmd == "list":
        for rule in UnifiPortForward().list_rules():
            print(
                f"{rule.get('name')}\t{rule.get('proto')}\t"
                f"{rule.get('dst_port')}->{rule.get('fwd')}:{rule.get('fwd_port')}\t"
                f"enabled={rule.get('enabled')}"
            )


if __name__ == "__main__":
    main()
