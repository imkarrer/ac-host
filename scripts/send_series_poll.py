#!/usr/bin/env python3
"""One-shot: DM Series #1 poll to product-manager role members."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import discord

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "shared"))

from series_poll import PM_ROLE_DEFAULT, send_pm_review  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class PollClient(discord.Client):
    def __init__(self, guild_id: int, pm_role: str) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(intents=intents)
        self.guild_id = guild_id
        self.pm_role = pm_role
        self.result: tuple[int, list[str]] | None = None

    async def on_ready(self) -> None:
        guild = self.get_guild(self.guild_id)
        if guild is None:
            guild = await self.fetch_guild(self.guild_id)
        channel = await self.user.create_dm()
        try:
            self.result = await send_pm_review(guild=guild, pm_role_name=self.pm_role, sender=channel)
        except RuntimeError as exc:
            await channel.send(f"Failed: {exc}")
        await self.close()


async def run() -> None:
    for path in (ROOT / ".env", ROOT / "compose" / ".env"):
        load_dotenv(path)
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    guild_raw = os.environ.get("DISCORD_GUILD_ID", "1544532113615749210").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set")
    pm_role = os.environ.get("DISCORD_PM_ROLE", PM_ROLE_DEFAULT)
    client = PollClient(int(guild_raw), pm_role)
    await client.start(token)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
