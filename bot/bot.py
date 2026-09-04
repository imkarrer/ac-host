#!/usr/bin/env python3
"""Discord bot: players request Steam links; admins approve/deny."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import discord
from discord import app_commands
from discord.ext import commands

from steam_parse import parse_profile, steam64_from_xml, vanity_slug
import car_skins
from players import (
    NOT_BOT_REGISTERED,
    clear_livery,
    find_livery_holder,
    find_player,
    format_livery,
    player_for_discord,
    player_public_name,
    set_livery,
    utcnow,
)

WHITELIST_PATH = Path(os.environ.get("WHITELIST_PATH", "/data/whitelist.json"))
PENDING_PATH = Path(os.environ.get("STEAM_REQUESTS_PATH") or (WHITELIST_PATH.parent / "steam_requests.json"))
CONTENT_PATH = Path(os.environ.get("AC_CONTENT", "/content"))
CATALOG_PATH = Path(os.environ.get("AC_CATALOG", "/catalog"))
REQUIRED_ROLE = os.environ.get("DISCORD_REQUIRED_ROLE", "ac-practice")
ADMIN_ROLE = os.environ.get("DISCORD_ADMIN_ROLE", "ac-admin")
_raw_channel = os.environ.get("DISCORD_REVIEW_CHANNEL_ID", "").strip()
REVIEW_CHANNEL_ID = int(_raw_channel) if _raw_channel.isdigit() else 0
VERIFY_PROFILE_HTTP = os.environ.get("DISCORD_VERIFY_PROFILE", "1") != "0"


def load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data if isinstance(data, dict) else default


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_whitelist() -> dict:
    return load_json(WHITELIST_PATH, {"players": []})


def save_whitelist(data: dict) -> None:
    save_json(WHITELIST_PATH, data)


def load_pending() -> dict:
    return load_json(PENDING_PATH, {"requests": []})


def save_pending(data: dict) -> None:
    save_json(PENDING_PATH, data)


def fetch_steam(url: str, *, limit: int = 8000) -> tuple[int, str] | tuple[None, str]:
    try:
        req = Request(
            url,
            headers={"User-Agent": "ac-host-bot/1 (+whitelist)"},
            method="GET",
        )
        with urlopen(req, timeout=8) as resp:
            body = resp.read(limit).decode("utf-8", errors="replace")
            code = getattr(resp, "status", 200)
    except HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except URLError as exc:
        return None, str(exc.reason if hasattr(exc, "reason") else exc)
    except OSError as exc:
        return None, str(exc)
    return code, body


def profile_reachable(url: str) -> tuple[bool, str]:
    """Best-effort check that Steam returns a profile page (not a hard 404)."""
    if not VERIFY_PROFILE_HTTP:
        return True, "skipped"
    code, body = fetch_steam(url)
    if code is None:
        return False, body
    if code >= 400:
        return False, f"HTTP {code}"
    lowered = body.lower()
    if "the specified profile could not be found" in lowered:
        return False, "Steam says profile not found"
    if "profile is private" in lowered or "this profile is private" in lowered:
        return True, "private (ok)"
    return True, "ok"


def resolve_vanity(slug: str) -> tuple[str, str] | tuple[None, str]:
    """Turn /id/slug into SteamID64 via Steam's public XML profile."""
    xml_url = f"https://steamcommunity.com/id/{slug}/?xml=1"
    code, body = fetch_steam(xml_url, limit=16000)
    if code is None:
        return None, body
    if code >= 400:
        return None, f"HTTP {code}"
    steam_id = steam64_from_xml(body)
    if not steam_id:
        return None, "Steam XML had no SteamID64"
    return steam_id, f"https://steamcommunity.com/profiles/{steam_id}"


def member_role_names(member: discord.Member) -> list[str]:
    return [role.name for role in member.roles if role.name != "@everyone"]


def is_admin(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild:
        return True
    return ADMIN_ROLE in member_role_names(member)


def upsert_player(
    data: dict,
    *,
    steam_id: str,
    member: discord.Member,
    profile_url: str,
    enabled: bool = True,
) -> None:
    roles = member_role_names(member)
    if enabled and REQUIRED_ROLE not in roles:
        roles = [*roles, REQUIRED_ROLE]
    players = data.setdefault("players", [])
    for player in players:
        if player.get("discord_id") == str(member.id) or player.get("steam_id") == steam_id:
            player.update(
                {
                    "steam_id": steam_id,
                    "discord_id": str(member.id),
                    "discord_name": str(member),
                    "profile_url": profile_url,
                    "roles": roles,
                    "enabled": enabled,
                    "linked_at": player.get("linked_at") or utcnow(),
                }
            )
            return
    players.append(
        {
            "steam_id": steam_id,
            "discord_id": str(member.id),
            "discord_name": str(member),
            "profile_url": profile_url,
            "roles": roles,
            "enabled": enabled,
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


def find_pending(requests: list[dict], *, discord_id: str | None = None, request_id: str | None = None) -> dict | None:
    for item in requests:
        if item.get("status") != "pending":
            continue
        if request_id and item.get("id") == request_id:
            return item
        if discord_id and item.get("discord_id") == discord_id:
            return item
    return None


def request_embed(item: dict, *, status: str | None = None) -> discord.Embed:
    state = status or item.get("status") or "pending"
    color = {
        "pending": discord.Color.blurple(),
        "approved": discord.Color.green(),
        "denied": discord.Color.red(),
    }.get(state, discord.Color.greyple())
    embed = discord.Embed(
        title=f"Steam link request ({state})",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Discord", value=f"<@{item['discord_id']}>\n`{item.get('discord_name')}`", inline=True)
    embed.add_field(name="SteamID64", value=f"`{item['steam_id']}`", inline=True)
    embed.add_field(name="Profile", value=item["profile_url"], inline=False)
    embed.set_footer(text=f"request {item['id']}")
    return embed


class PersistentReviewView(discord.ui.View):
    """Persistent buttons; request id is read from the embed footer."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="ac_host:steam_approve")
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_button(interaction, approve=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="ac_host:steam_deny")
    async def deny(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_button(interaction, approve=False)


async def handle_button(interaction: discord.Interaction, *, approve: bool) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(
            f"Only `{ADMIN_ROLE}` (or Manage Server) can review requests.",
            ephemeral=True,
        )
        return
    if not interaction.message or not interaction.message.embeds:
        await interaction.response.send_message("Missing request embed.", ephemeral=True)
        return
    footer = interaction.message.embeds[0].footer.text or ""
    request_id = footer.replace("request ", "").strip()
    if not request_id:
        await interaction.response.send_message("Could not read request id.", ephemeral=True)
        return
    await finalize_request(interaction, request_id, approve=approve)


async def finalize_request(interaction: discord.Interaction, request_id: str, *, approve: bool) -> None:
    pending = load_pending()
    item = find_pending(pending.get("requests") or [], request_id=request_id)
    if not item:
        await interaction.response.send_message("No pending request with that id (already handled?).", ephemeral=True)
        return

    guild = interaction.guild
    member = guild.get_member(int(item["discord_id"])) if guild else None
    if member is None and guild:
        try:
            member = await guild.fetch_member(int(item["discord_id"]))
        except discord.HTTPException:
            member = None

    if approve:
        if member is None:
            await interaction.response.send_message(
                "Approved Steam id, but Discord member is not in the server anymore.",
                ephemeral=True,
            )
            # still write whitelist with stored discord_id
            data = load_whitelist()
            players = data.setdefault("players", [])
            players.append(
                {
                    "steam_id": item["steam_id"],
                    "discord_id": item["discord_id"],
                    "discord_name": item.get("discord_name") or "",
                    "profile_url": item["profile_url"],
                    "roles": [REQUIRED_ROLE],
                    "enabled": True,
                    "linked_at": utcnow(),
                }
            )
            save_whitelist(data)
        else:
            data = load_whitelist()
            upsert_player(
                data,
                steam_id=item["steam_id"],
                member=member,
                profile_url=item["profile_url"],
                enabled=True,
            )
            save_whitelist(data)
            role = discord.utils.get(guild.roles, name=REQUIRED_ROLE) if guild else None
            if role and role not in member.roles and guild.me.top_role > role:
                try:
                    await member.add_roles(role, reason="Steam link approved")
                except discord.HTTPException:
                    pass
        item["status"] = "approved"
        item["resolved_at"] = utcnow()
        item["resolved_by"] = str(interaction.user.id)
        save_pending(pending)
        await interaction.response.edit_message(embed=request_embed(item), view=None)
        if member:
            try:
                await member.send(
                    f"Your Steam link was **approved**. Profile: {item['profile_url']}\n"
                    f"You can join the practice lobbies (role `{REQUIRED_ROLE}`)."
                )
            except discord.HTTPException:
                pass
        return

    item["status"] = "denied"
    item["resolved_at"] = utcnow()
    item["resolved_by"] = str(interaction.user.id)
    save_pending(pending)
    await interaction.response.edit_message(embed=request_embed(item), view=None)
    if member:
        try:
            await member.send("Your Steam link request was **denied**. Ask an admin if you think that was a mistake.")
        except discord.HTTPException:
            pass


class LobbyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # Server Members Intent is privileged — enable in the Discord portal
        # if you want live role sync (on_member_update). Approve flow uses fetch_member.
        if os.environ.get("DISCORD_MEMBERS_INTENT", "0") == "1":
            intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self._commands_synced = False

    async def setup_hook(self) -> None:
        self.add_view(PersistentReviewView())
        # Global sync can take up to an hour to show in the Discord client.
        # Guild sync is immediate — do that in on_ready once we know the servers.


async def sync_guild_commands() -> None:
    if bot._commands_synced:
        return
    # Earlier deploys registered GLOBAL commands. Discord keeps those IDs for up
    # to an hour and replies "This command is outdated" if someone clicks them.
    leftover = await bot.tree.fetch_commands()
    if leftover:
        await bot.http.bulk_upsert_global_commands(bot.application_id, [])
        print(f"cleared {len(leftover)} leftover global commands")
    for guild in bot.guilds:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"synced {len(synced)} commands to guild={guild.id} ({guild.name})")
    bot._commands_synced = True


bot = LobbyBot()


async def car_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    cars = car_skins.list_practice_cars(CONTENT_PATH, CATALOG_PATH)
    cur = current.lower()
    choices = []
    for folder, name in cars:
        label = f"{name} ({folder})"
        if cur and cur not in label.lower() and cur not in folder.lower():
            continue
        choices.append(app_commands.Choice(name=label[:100], value=folder))
        if len(choices) >= 25:
            break
    return choices


async def skin_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    car = ""
    if interaction.namespace:
        car = str(getattr(interaction.namespace, "car", "") or "")
    if not car:
        return []
    skins = car_skins.list_skins(CONTENT_PATH, car)
    cur = current.lower()
    choices = []
    for skin in skins:
        if cur and cur not in skin.lower():
            continue
        choices.append(app_commands.Choice(name=skin[:100], value=skin))
        if len(choices) >= 25:
            break
    return choices


@bot.event
async def on_ready() -> None:
    print(f"bot ready as {bot.user} guilds={len(bot.guilds)} review_channel={REVIEW_CHANNEL_ID}")
    print(f"content={CONTENT_PATH} cars={len(car_skins.list_practice_cars(CONTENT_PATH, CATALOG_PATH))}")
    await sync_guild_commands()


@bot.tree.command(name="steam-help", description="How to request access to the AC practice lobbies")
async def steam_help(interaction: discord.Interaction) -> None:
    text = (
        "**We accept either Steam profile link**\n"
        "• `https://steamcommunity.com/id/yourname`  ← what Steam usually copies\n"
        "• `https://steamcommunity.com/profiles/7656119…`  ← the numeric one\n"
        "Paste whichever **Copy Page URL** gives you. Both work.\n\n"
        "**Register**\n"
        "1. Steam → your name → **View my profile**.\n"
        "2. Right‑click the page → **Copy Page URL**.\n"
        "3. Here: `/steam-request` and paste that URL.\n"
        "4. Wait for an admin to **Approve** (you’ll get a DM if possible).\n"
        "5. Join from Content Manager after you’re approved.\n\n"
        "**Livery (one car + color)**\n"
        "After the bot has approved you: `/livery-set` → pick car → pick color. "
        "Only **one** preference (run it again to replace). "
        "Each car+color can be reserved by **one** person. "
        "Your pick is posted in the channel. Applies after the next lobby restart.\n"
        "`/livery-show` · `/livery-clear`\n"
        "If you were added by hand, `/livery-set` fails until you `/steam-request` and get approved."
    )
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="livery-set", description="Reserve ONE car + color for practice (uses your Steam link)")
@app_commands.describe(car="Car on the practice servers", skin="Livery / color for that car")
@app_commands.autocomplete(car=car_autocomplete, skin=skin_autocomplete)
async def livery_set(interaction: discord.Interaction, car: str, skin: str) -> None:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    cars = {folder for folder, _ in car_skins.list_practice_cars(CONTENT_PATH, CATALOG_PATH)}
    if car not in cars:
        await interaction.response.send_message(f"Unknown car `{car}`.", ephemeral=True)
        return
    skins = car_skins.list_skins(CONTENT_PATH, car)
    if skin not in skins:
        await interaction.response.send_message(
            f"Unknown skin `{skin}` for `{car}`. Pick from the autocomplete list.",
            ephemeral=True,
        )
        return
    data = load_whitelist()
    player = player_for_discord(data, str(interaction.user.id))
    if not player:
        await interaction.response.send_message(NOT_BOT_REGISTERED, ephemeral=True)
        return
    holder = find_livery_holder(
        data,
        car,
        skin,
        except_steam=str(player.get("steam_id") or ""),
        except_discord=str(interaction.user.id),
    )
    if holder:
        await interaction.response.send_message(
            f"{player_public_name(holder)} already took **{car}** / **{skin}**. "
            "Pick a different color (or car).",
            ephemeral=True,
        )
        return
    set_livery(player, car, skin)
    save_whitelist(data)
    await interaction.response.send_message(
        f"{interaction.user.mention} picked **{car}** / **{skin}**. "
        "Reserved for their Steam ID after the next practice lobby restart.",
        ephemeral=False,
    )


@bot.tree.command(name="livery-show", description="Show your saved car/color preference")
async def livery_show(interaction: discord.Interaction) -> None:
    data = load_whitelist()
    player = player_for_discord(data, str(interaction.user.id))
    if not player:
        await interaction.response.send_message(NOT_BOT_REGISTERED, ephemeral=True)
        return
    await interaction.response.send_message(
        f"Your livery preference: {format_livery(player)}\nSteam: `{player.get('steam_id')}`",
        ephemeral=True,
    )


@bot.tree.command(name="livery-clear", description="Remove your car/color preference")
async def livery_clear(interaction: discord.Interaction) -> None:
    data = load_whitelist()
    player = player_for_discord(data, str(interaction.user.id))
    if not player:
        await interaction.response.send_message(NOT_BOT_REGISTERED, ephemeral=True)
        return
    if clear_livery(player):
        save_whitelist(data)
        await interaction.response.send_message(
            "Cleared. You’ll get the server default after the next lobby restart.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message("You had no preference set.", ephemeral=True)


@bot.tree.command(
    name="livery-admin-set",
    description="Admin: set car/color for a Steam ID (backfill / test without Discord link)",
)
@app_commands.describe(
    steam="SteamID64 of the driver",
    car="Car folder id",
    skin="Skin folder name",
)
@app_commands.autocomplete(car=car_autocomplete, skin=skin_autocomplete)
async def livery_admin_set(
    interaction: discord.Interaction, steam: str, car: str, skin: str
) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(f"Need `{ADMIN_ROLE}` or Manage Server.", ephemeral=True)
        return
    steam_id = steam.strip()
    if not steam_id.startswith("7656119") or len(steam_id) != 17:
        await interaction.response.send_message("Need a 17-digit SteamID64.", ephemeral=True)
        return
    cars = {folder for folder, _ in car_skins.list_practice_cars(CONTENT_PATH, CATALOG_PATH)}
    if car not in cars or skin not in car_skins.list_skins(CONTENT_PATH, car):
        await interaction.response.send_message("Invalid car/skin combo.", ephemeral=True)
        return
    data = load_whitelist()
    holder = find_livery_holder(data, car, skin, except_steam=steam_id)
    if holder:
        await interaction.response.send_message(
            f"{player_public_name(holder)} already took **{car}** / **{skin}**.",
            ephemeral=True,
        )
        return
    player = find_player(data, steam_id=steam_id)
    if not player:
        player = {
            "steam_id": steam_id,
            "discord_id": "0",
            "discord_name": "",
            "roles": [REQUIRED_ROLE],
            "enabled": True,
            "linked_at": utcnow(),
        }
        data.setdefault("players", []).append(player)
    set_livery(player, car, skin)
    save_whitelist(data)
    await interaction.response.send_message(
        f"Set `{steam_id}` → **{car}** / **{skin}**. Restart practice lobbies to apply.",
        ephemeral=True,
    )


@bot.tree.command(
    name="steam-request",
    description="Request access — paste either /id/ or /profiles/ Steam URL",
)
@app_commands.describe(
    profile="Either https://steamcommunity.com/id/name OR /profiles/7656… — both work"
)
async def steam_request(interaction: discord.Interaction, profile: str) -> None:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return

    parsed = parse_profile(profile)
    slug = None if parsed else vanity_slug(profile)
    if not parsed and not slug:
        await interaction.response.send_message(
            "Need a Steam profile URL — **either** form is fine:\n"
            "`https://steamcommunity.com/id/yourname`\n"
            "`https://steamcommunity.com/profiles/76561198000000000`\n"
            "Steam → View my profile → right‑click → **Copy Page URL**, then paste that.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    if parsed:
        steam_id, profile_url = parsed
    else:
        resolved = resolve_vanity(slug or "")
        if resolved[0] is None:
            await interaction.followup.send(
                f"Could not resolve that `/id/` link ({resolved[1]}). "
                "Open it in a browser and confirm it is your Steam profile, then try again.",
                ephemeral=True,
            )
            return
        steam_id, profile_url = resolved

    ok, reason = profile_reachable(profile_url)
    if not ok:
        await interaction.followup.send(
            f"Could not verify that profile ({reason}). "
            f"Open {profile_url} in a browser, confirm it loads, then try again.",
            ephemeral=True,
        )
        return

    pending = load_pending()
    requests = pending.setdefault("requests", [])
    existing = find_pending(requests, discord_id=str(interaction.user.id))
    if existing:
        await interaction.followup.send(
            f"You already have a pending request (`{existing['id']}`). Wait for an admin to review it.",
            ephemeral=True,
        )
        return

    request_id = secrets.token_hex(4)
    item = {
        "id": request_id,
        "discord_id": str(interaction.user.id),
        "discord_name": str(interaction.user),
        "steam_id": steam_id,
        "profile_url": profile_url,
        "status": "pending",
        "created_at": utcnow(),
        "profile_check": reason,
    }
    requests.append(item)
    save_pending(pending)

    view = PersistentReviewView()
    embed = request_embed(item)
    posted = False
    if REVIEW_CHANNEL_ID and interaction.guild:
        channel = interaction.guild.get_channel(REVIEW_CHANNEL_ID)
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(REVIEW_CHANNEL_ID)
            except discord.HTTPException:
                channel = None
        if isinstance(channel, discord.TextChannel):
            role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE)
            content = role.mention if role else f"Admin review needed (`{ADMIN_ROLE}`)"
            msg = await channel.send(content=content, embed=embed, view=view)
            item["message_id"] = str(msg.id)
            item["channel_id"] = str(channel.id)
            save_pending(pending)
            posted = True

    if posted:
        await interaction.followup.send(
            f"Request submitted. Admins will review your profile:\n{profile_url}",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(
            f"Request `{request_id}` saved, but **no review channel** is configured "
            f"(`DISCORD_REVIEW_CHANNEL_ID`). Tell an admin to set that, or use "
            f"`/steam-approve` / `/steam-deny`.\nProfile: {profile_url}",
            ephemeral=True,
        )


@bot.tree.command(name="steam-approve", description="Admin: approve a pending Steam link for a user")
@app_commands.describe(user="Discord member to approve", request_id="Optional pending request id")
async def steam_approve(
    interaction: discord.Interaction,
    user: discord.Member,
    request_id: str | None = None,
) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(f"Need `{ADMIN_ROLE}` or Manage Server.", ephemeral=True)
        return
    pending = load_pending()
    item = find_pending(pending.get("requests") or [], request_id=request_id, discord_id=str(user.id))
    if not item:
        await interaction.response.send_message("No pending request for that user.", ephemeral=True)
        return
    # Reuse finalize via a fake edit path: apply whitelist directly
    data = load_whitelist()
    upsert_player(data, steam_id=item["steam_id"], member=user, profile_url=item["profile_url"], enabled=True)
    save_whitelist(data)
    item["status"] = "approved"
    item["resolved_at"] = utcnow()
    item["resolved_by"] = str(interaction.user.id)
    save_pending(pending)
    role = discord.utils.get(interaction.guild.roles, name=REQUIRED_ROLE) if interaction.guild else None
    if role and role not in user.roles and interaction.guild and interaction.guild.me.top_role > role:
        try:
            await user.add_roles(role, reason="Steam link approved")
        except discord.HTTPException:
            pass
    await interaction.response.send_message(
        f"Approved {user.mention} → `{item['steam_id']}` ({item['profile_url']})",
        ephemeral=True,
    )


@bot.tree.command(name="steam-deny", description="Admin: deny a pending Steam link request")
@app_commands.describe(user="Discord member to deny")
async def steam_deny(interaction: discord.Interaction, user: discord.Member) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(f"Need `{ADMIN_ROLE}` or Manage Server.", ephemeral=True)
        return
    pending = load_pending()
    item = find_pending(pending.get("requests") or [], discord_id=str(user.id))
    if not item:
        await interaction.response.send_message("No pending request for that user.", ephemeral=True)
        return
    item["status"] = "denied"
    item["resolved_at"] = utcnow()
    item["resolved_by"] = str(interaction.user.id)
    save_pending(pending)
    await interaction.response.send_message(f"Denied request from {user.mention}.", ephemeral=True)


@bot.tree.command(name="steam-unlink", description="Admin: disable a user's Steam whitelist entry")
@app_commands.describe(user="Discord member to unlink")
async def steam_unlink(interaction: discord.Interaction, user: discord.Member) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(f"Need `{ADMIN_ROLE}` or Manage Server.", ephemeral=True)
        return
    data = load_whitelist()
    if disable_discord(data, str(user.id)):
        save_whitelist(data)
        await interaction.response.send_message(
            f"Disabled whitelist for {user.mention}. They will be denied on the next join.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message("No whitelist row for that user.", ephemeral=True)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    if not bot.intents.members:
        return
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
        # Keep enabled unless admin unlinked; only auto-disable if practice role removed
        if REQUIRED_ROLE not in player["roles"]:
            player["enabled"] = False
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
