#!/usr/bin/env python3
"""Link Discord users to SteamID64 and write the shared whitelist."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

STEAM64 = re.compile(r"7656119\d{10}")
WHITELIST_PATH = Path(os.environ["WHITELIST_PATH"])
REQUIRED_ROLE = os.environ.get("DISCORD_REQUIRED_ROLE", "ac-practice")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_whitelist() -> dict:
    if not WHITELIST_PATH.is_file():
        return {"players": []}
    return json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))


def save_whitelist(data: dict) -> None:
    WHITELIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WHITELIST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(WHITELIST_PATH)


def parse_steam_id(raw: str) -> str | None:
    match = STEAM64.search(raw.strip())
    return match.group(0) if match else None


def member_role_names(member: discord.Member) -> list[str]:
    return [role.name for role in member.roles if role.name != "@everyone"]


def upsert_player(data: dict, *, steam_id: str, member: discord.Member) -> None:
    roles = member_role_names(member)
    players = data.setdefault("players", [])
    for player in players:
        if player.get("discord_id") == str(member.id) or player.get("steam_id") == steam_id:
            player.update(
                {
                    "steam_id": steam_id,
                    "discord_id": str(member.id),
                    "discord_name": str(member),
                    "roles": roles,
                    "enabled": REQUIRED_ROLE in roles,
                    "linked_at": player.get("linked_at") or utcnow(),
                }
            )
            return
    players.append(
        {
            "steam_id": steam_id,
            "discord_id": str(member.id),
            "discord_name": str(member),
            "roles": roles,
            "enabled": REQUIRED_ROLE in roles,
            "linked_at": utcnow(),
        }
    )


def disable_discord(data: dict, discord_id: str) -> bool:
    found = False
    for player in data.get("players") or []:
        if player.get("discord_id") == discord_id:
            player["enabled"] = False
            found = True
    return found


class LobbyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await self.tree.sync()


bot = LobbyBot()


@bot.tree.command(name="steam-link", description="Link your SteamID64 so you can join the AC lobby")
@app_commands.describe(steam="SteamID64 or steamcommunity.com/profiles/… URL")
async def steam_link(interaction: discord.Interaction, steam: str) -> None:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    steam_id = parse_steam_id(steam)
    if not steam_id:
        await interaction.response.send_message(
            "Need a SteamID64 (starts with 7656119) or a /profiles/ URL. "
            "Vanity /id/ URLs are not resolved yet.",
            ephemeral=True,
        )
        return
    data = load_whitelist()
    upsert_player(data, steam_id=steam_id, member=interaction.user)
    save_whitelist(data)
    has_role = REQUIRED_ROLE in member_role_names(interaction.user)
    if has_role:
        await interaction.response.send_message(
            f"Linked `{steam_id}`. You can join the practice lobby.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"Linked `{steam_id}`, but you need the `{REQUIRED_ROLE}` role before the server will let you in.",
            ephemeral=True,
        )


@bot.tree.command(name="steam-unlink", description="Remove your Steam link")
async def steam_unlink(interaction: discord.Interaction) -> None:
    data = load_whitelist()
    if disable_discord(data, str(interaction.user.id)):
        save_whitelist(data)
        await interaction.response.send_message("Unlinked. You will be denied on the next join.", ephemeral=True)
    else:
        await interaction.response.send_message("No Steam ID stored for you.", ephemeral=True)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    before_roles = set(member_role_names(before))
    after_roles = set(member_role_names(after))
    if before_roles == after_roles:
        return
    data = load_whitelist()
    changed = False
    for player in data.get("players") or []:
        if player.get("discord_id") != str(after.id):
            continue
        player["roles"] = member_role_names(after)
        player["enabled"] = REQUIRED_ROLE in player["roles"]
        changed = True
    if changed:
        save_whitelist(data)


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set")
    bot.run(token)


if __name__ == "__main__":
    main()
