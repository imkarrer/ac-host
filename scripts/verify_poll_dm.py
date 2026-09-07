#!/usr/bin/env python3
"""Verify Series #1 poll DM was created (reads Discord REST, no secrets printed)."""
import json
import urllib.request
from pathlib import Path

env = {}
for line in Path("/var/lib/ac-host/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
token = env["DISCORD_TOKEN"]
uid = env.get("DISCORD_PM_USER_IDS", "277926733989150727").split(",")[0].strip()
h = {"Authorization": f"Bot {token}", "User-Agent": "ac-host-poll-verify/1"}

# Open or reuse DM
dm = json.loads(
    urllib.request.urlopen(
        urllib.request.Request(
            "https://discord.com/api/v10/users/@me/channels",
            data=json.dumps({"recipient_id": uid}).encode(),
            headers={**h, "Content-Type": "application/json"},
            method="POST",
        )
    ).read()
)
cid = dm["id"]
msgs = json.loads(
    urllib.request.urlopen(
        urllib.request.Request(f"https://discord.com/api/v10/channels/{cid}/messages?limit=15", headers=h)
    ).read()
)
print(f"dm_channel={cid} recipient={uid}")
print(f"message_count={len(msgs)}")
for m in reversed(msgs):
    kind = "poll" if m.get("poll") else "text"
    preview = (m.get("content") or m.get("poll", {}).get("question", {}).get("text") or "")[:60]
    print(f"  id={m['id']} type={kind} preview={preview!r}")
