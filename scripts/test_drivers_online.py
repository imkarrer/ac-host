"""drivers_online.py is the platform's busyCheck: exit 0 = BUSY.

These pin the three answers that matter to homelab's deploy unit, using a
real local HTTP server per case rather than mocking urllib -- the failure
modes under test (refused vs. listening-but-broken) are socket behaviours.
"""

from __future__ import annotations

import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drivers_online  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Lobby(HTTPServer):
    """A fake acServer answering /api/details with a fixed body."""

    def __init__(self, body: bytes):
        self.body = body
        super().__init__(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.server.body)

    def log_message(self, *_):
        pass


class DriversOnlineTests(unittest.TestCase):
    def _run_against(self, ports):
        """Point the module's slot arithmetic at exactly the given ports."""
        old = (drivers_online.DETAILS_START, drivers_online.SLOT_COUNT)
        try:
            # Contiguous range starting at the first port; unused slots are refused.
            drivers_online.DETAILS_START = ports[0]
            drivers_online.SLOT_COUNT = (max(ports) - ports[0]) + 1
            return drivers_online.main()
        finally:
            drivers_online.DETAILS_START, drivers_online.SLOT_COUNT = old

    def test_no_lobbies_is_not_busy(self):
        # Nothing listening on any slot: connection refused everywhere. An
        # empty box has nobody to disturb.
        p = _free_port()
        self.assertEqual(self._run_against([p]), 1)

    def test_empty_lobbies_are_not_busy(self):
        a = _Lobby(json.dumps({"clients": 0}).encode())
        b = _Lobby(json.dumps({"clients": 0}).encode())
        try:
            self.assertEqual(self._run_against(sorted([a.port, b.port])), 1)
        finally:
            a.stop()
            b.stop()

    def test_one_driver_anywhere_is_busy(self):
        a = _Lobby(json.dumps({"clients": 0}).encode())
        b = _Lobby(json.dumps({"clients": 1}).encode())
        try:
            self.assertEqual(self._run_against(sorted([a.port, b.port])), 0)
        finally:
            a.stop()
            b.stop()

    def test_listening_but_unparseable_fails_closed(self):
        # A lobby that answers garbage might have drivers. Treat as busy.
        a = _Lobby(b"not json")
        try:
            self.assertEqual(self._run_against([a.port]), 0)
        finally:
            a.stop()

    def test_clients_not_an_int_fails_closed(self):
        a = _Lobby(json.dumps({"clients": "many"}).encode())
        try:
            self.assertEqual(self._run_against([a.port]), 0)
        finally:
            a.stop()


if __name__ == "__main__":
    unittest.main()
