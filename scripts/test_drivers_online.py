"""drivers_online.py is the platform's busyCheck: exit 0 = BUSY.

These pin the three answers that matter to homelab's deploy unit, using a
real local HTTP server per case rather than mocking urllib -- the failure
modes under test (refused vs. listening-but-broken) are socket behaviours.
"""

from __future__ import annotations

import errno
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
    """A fake acServer answering /api/details with a fixed body.

    ``port`` 0 lets the kernel choose; a fixed port raises OSError
    (EADDRINUSE) if something else holds it, which _adjacent_lobbies relies on.
    """

    def __init__(self, body: bytes, port: int = 0):
        self.body = body
        super().__init__(("127.0.0.1", port), _Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


def _adjacent_lobbies(body_a: bytes, body_b: bytes) -> tuple[_Lobby, _Lobby]:
    """Two lobbies on ports p and p+1, so _run_against scans exactly those two.

    Never bind two lobbies on independent ephemeral ports and scan the range
    between them: every port in that gap has nothing listening, and when the
    kernel hands the probe a source port equal to the one it is probing, Linux
    completes a TCP self-connect and urlopen reads back its own request line
    (BadStatusLine). Seen roughly 1 run in 8 before this helper existed.
    """
    for _ in range(50):
        p = _free_port()
        if p >= 65535:
            continue
        try:
            a = _Lobby(body_a, p)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            continue
        try:
            b = _Lobby(body_b, p + 1)
        except OSError as exc:
            a.stop()
            if exc.errno != errno.EADDRINUSE:
                raise
            continue
        return a, b
    raise RuntimeError("could not find two adjacent free ports on 127.0.0.1")


class _BrokenLobby:
    """A socket that is listening but does not speak HTTP.

    Accepts each connection, writes a line that is not an HTTP status line, and
    closes. This is the "listening but broken" shape the module docstring says
    fails closed; urlopen surfaces it as http.client.BadStatusLine, which is
    not a URLError.
    """

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return  # stop() shut the listener down
            with conn:
                try:
                    conn.recv(1024)  # let the client finish sending its request
                    conn.sendall(b"nonsense\r\n")
                except OSError:
                    pass

    def stop(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)  # wakes the blocked accept()
        except OSError:
            pass
        self.sock.close()
        self.thread.join(timeout=2)


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
        a, b = _adjacent_lobbies(
            json.dumps({"clients": 0}).encode(),
            json.dumps({"clients": 0}).encode(),
        )
        try:
            self.assertEqual(self._run_against([a.port, b.port]), 1)
        finally:
            a.stop()
            b.stop()

    def test_one_driver_anywhere_is_busy(self):
        a, b = _adjacent_lobbies(
            json.dumps({"clients": 0}).encode(),
            json.dumps({"clients": 1}).encode(),
        )
        try:
            self.assertEqual(self._run_against([a.port, b.port]), 0)
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

    def test_listening_but_not_http_fails_closed(self):
        # Accepts the connection, answers a line that is not HTTP. urlopen
        # raises http.client.BadStatusLine here, not URLError; before this was
        # caught, the traceback exited 1 and the deploy unit read NOT busy.
        a = _BrokenLobby()
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
