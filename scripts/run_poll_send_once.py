#!/usr/bin/env python3
"""One-shot poll send — run inside bot container: python /app/run_poll_send_once.py"""

from __future__ import annotations

import asyncio
import os

import discord
from series_poll import PM_ROLE_DEFAULT, send_pm_review


class PollSender(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)

    async def on_ready(self) -> None:
        gid = int(os.environ.get("DISCORD_GUILD_ID", "1544532113615749210"))
        guild = self.get_guild(gid) or await self.fetch_guild(gid)
        pm = os.environ.get("DISCORD_PM_ROLE", PM_ROLE_DEFAULT)
        dm = await self.user.create_dm()
        try:
            sent, errs = await send_pm_review(guild=guild, pm_role_name=pm, sender=dm)
            print(f"OK sent={sent} errors={errs}")
        except Exception as exc:
            print(f"FAIL {exc}")
        await self.close()


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN missing")
    asyncio.run(PollSender().start(token))


if __name__ == "__main__":
    main()
