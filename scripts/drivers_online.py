#!/usr/bin/env python3
"""Is anyone racing? Exit 0 if yes (BUSY), 1 if no. The platform's busyCheck.

homelab's tenant contract gives assetto ``quiet.busyCheck``, and its deploy
unit (modules/deploy) runs that check before switching the system closure:
BUSY defers the switch to the next window. Until 12 Sep 2026 the check was
``test ! -e /var/lib/ac-host/maintenance.json`` -- BUSY whenever the box had
not been explicitly drained, i.e. essentially always. That was homelab bead
.34's finding ("interpreted, not verified"), and once the deploy unit existed
it stopped being merely conservative: the unit fires at 03:00, the bot's
DOWNTIME=1 build that performs the drain is picked up seconds to minutes
later, and the unit would lose that race and defer every night, forever.

This asks acServer itself. Each running lobby serves ``/api/details`` on its
details port (``DETAILS_START + slot``, the same arithmetic acctl.py uses),
and that JSON carries ``clients``, the live connected-driver count -- the
number Content Manager shows. No file freshness to reason about, no sidecar
in the path.

Fail closed, deliberately. A lobby that is LISTENING but does not answer, or
answers something unparseable, counts as busy: a lobby that will not tell you
whether it has drivers might. A port with nothing listening (connection
refused) is simply not a lobby and counts as nothing. So an empty box with no
lobbies up reports NOT busy -- correct, there is nobody to disturb -- while a
wedged lobby reports busy -- correct, the switch can wait.

Runs anywhere python3 is; stdlib only. Also usable by a human:
``python3 drivers_online.py && echo racing || echo empty``.
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request

DETAILS_START = 8181  # acctl.py:DETAILS_START; slot n serves details on DETAILS_START + n
SLOT_COUNT = 16  # acctl.py:SLOT_COUNT; 9600-9615 is the whole game-port range
HOST = "127.0.0.1"
TIMEOUT_S = 2.0


def clients_on(port: int) -> int | None:
    """Connected drivers on the lobby at ``port``.

    Returns None when nothing is listening (not a lobby). Raises on a lobby
    that is listening but will not answer cleanly -- the caller treats that as
    busy.
    """
    url = f"http://{HOST}:{port}/api/details"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            data = json.load(resp)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ConnectionRefusedError) or (
            isinstance(reason, OSError) and getattr(reason, "errno", None) == 111
        ):
            return None
        raise
    clients = data.get("clients")
    if not isinstance(clients, int):
        raise ValueError(f"{url}: 'clients' is {clients!r}, not an int")
    return clients


def main() -> int:
    total = 0
    lobbies = 0
    for slot in range(SLOT_COUNT):
        port = DETAILS_START + slot
        try:
            n = clients_on(port)
        except (urllib.error.URLError, socket.timeout, ValueError, json.JSONDecodeError, OSError) as exc:
            print(f"busy: lobby on {port} did not answer cleanly ({exc}); failing closed", file=sys.stderr)
            return 0
        if n is None:
            continue
        lobbies += 1
        total += n
    if total > 0:
        print(f"busy: {total} driver(s) connected across {lobbies} lobby/lobbies", file=sys.stderr)
        return 0
    print(f"not busy: {lobbies} lobby/lobbies, 0 drivers", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
