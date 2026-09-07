#!/usr/bin/env python3
import json
import urllib.request
from pathlib import Path

env: dict[str, str] = {}
for line in Path("/var/lib/ac-host/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
token = env.get("DISCORD_TOKEN", "")
gid = env.get("DISCORD_GUILD_ID", "1544532113615749210")
h = {"Authorization": f"Bot {token}", "User-Agent": "ac-host-poll-probe"}
roles = json.loads(
    urllib.request.urlopen(
        urllib.request.Request(f"https://discord.com/api/v10/guilds/{gid}/roles", headers=h)
    ).read()
)
pm = [r for r in roles if r.get("name") in ("product-manager", "product manager")]
if not pm:
    print(
        "all_roles",
        [(r.get("name"), r.get("id")) for r in sorted(roles, key=lambda x: x.get("position", 0), reverse=True)],
    )
print("pm_role", pm[0]["id"] if pm else "NOT_FOUND")
if pm:
    rid = pm[0]["id"]
    try:
        req = urllib.request.Request(
            f"https://discord.com/api/v10/guilds/{gid}/members?limit=1000", headers=h
        )
        members = json.loads(urllib.request.urlopen(req).read())
        hits = [m for m in members if rid in (m.get("roles") or [])]
        print("members_with_role", [(m["user"]["username"], m["user"]["id"]) for m in hits])
    except Exception as exc:
        print("members_list_error", type(exc).__name__, exc)
