#!/usr/bin/env python3
import json
import urllib.parse
import urllib.request
from pathlib import Path

env: dict[str, str] = {}
for line in Path("/var/lib/ac-host/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
token = env.get("DISCORD_TOKEN", "")
gid = env.get("DISCORD_GUILD_ID", "1544532113615749210")
pm_role_id = "1545237197932724244"
h = {"Authorization": f"Bot {token}", "User-Agent": "ac-host-poll-probe"}
for q in ["max", "ferah", "ulf", "cys", "guinea", "m"]:
    url = f"https://discord.com/api/v10/guilds/{gid}/members/search?{urllib.parse.urlencode({'query': q, 'limit': 10})}"
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h)).read())
        hits = [
            (x["user"]["username"], x["user"]["id"], pm_role_id in (x.get("roles") or []))
            for x in data
        ]
        print(q, hits)
    except Exception as exc:
        print(q, type(exc).__name__, exc)
