#!/usr/bin/env python3
"""Set Isaac's test livery preference and print occupancy."""
import json
from pathlib import Path
from urllib.request import urlopen

p = Path("/var/lib/ac-host/whitelist.json")
data = json.loads(p.read_text(encoding="utf-8"))
for pl in data["players"]:
    if pl.get("steam_id") == "76561197961983498":
        pl["livery"] = {
            "car": "abarth_124_2016",
            "skin": "01_Nero",
            "updated_at": "prove-test",
        }
        print("set isaac livery", pl["livery"])
        break
else:
    raise SystemExit("isaac not found")
p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

for port in (8081, 8082, 8083, 8089):
    try:
        with urlopen(f"http://127.0.0.1:{port}/INFO", timeout=3) as resp:
            clients = json.loads(resp.read().decode()).get("clients", -1)
    except Exception as exc:
        clients = f"err:{exc}"
    print(f"port {port} clients={clients}")
