#!/usr/bin/env python3
"""Discord bot: players request Steam links; admins approve/deny."""

from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import discord
from discord import app_commands
from discord.ext import commands, tasks

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE, _HERE.parent / "shared"):
    if (_candidate / "downtime.py").is_file() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
        break

from steam_parse import parse_profile, steam64_from_xml, vanity_slug
import car_skins
import page_mirror
import downtime
from players import (
    NOT_BOT_REGISTERED,
    clear_livery,
    find_livery_holder,
    find_pending_item,
    find_pending_livery_combo,
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
_raw_status = os.environ.get("DISCORD_STATUS_CHANNEL_ID", "").strip()
STATUS_CHANNEL_ID = int(_raw_status) if _raw_status.isdigit() else 0
VERIFY_PROFILE_HTTP = os.environ.get("DISCORD_VERIFY_PROFILE", "1") != "0"
PUBLIC_IP = os.environ.get("AC_PUBLIC_IP", "").strip()
PAGES_URL = os.environ.get("AC_PAGES_URL", "https://simracing.fugazy.dev").strip()
STATICS_PATH = Path(os.environ.get("AC_CATALOG_STATICS") or (CATALOG_PATH / "statics.json"))
if not STATICS_PATH.is_absolute():
    STATICS_PATH = CATALOG_PATH / STATICS_PATH
LEADERBOARD_PATH = Path(os.environ.get("LEADERBOARD_PATH") or (WHITELIST_PATH.parent / "leaderboard.json"))
MIRROR_STATE_PATH = Path(os.environ.get("PAGE_MIRROR_PATH") or (WHITELIST_PATH.parent / "page_mirror.json"))


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
    data = load_json(PENDING_PATH, {"requests": [], "livery_requests": []})
    data.setdefault("requests", [])
    data.setdefault("livery_requests", [])
    return data


def save_pending(data: dict) -> None:
    save_json(PENDING_PATH, data)


def page_snapshot() -> dict:
    display = car_skins.load_car_display_names(CATALOG_PATH)
    cars = [name for _, name in car_skins.list_practice_cars(CONTENT_PATH, CATALOG_PATH)]
    if not cars:
        cars = [display.get(folder) or folder for folder in car_skins.PRACTICE_CARS]
    return page_mirror.snapshot(
        statics=page_mirror.load_statics(STATICS_PATH),
        board=page_mirror.load_json(LEADERBOARD_PATH, {"updated": None, "lobbies": {}}),
        public_ip=PUBLIC_IP or "127.0.0.1",
        pages_url=PAGES_URL,
        cars=cars,
    )


def snapshot_embed(snap: dict) -> discord.Embed:
    embed = discord.Embed(
        title=snap["title"],
        description=snap["description"],
        color=snap["color"],
        url=snap.get("url") or None,
    )
    for field in snap["fields"]:
        embed.add_field(name=field["name"], value=field["value"][:1024], inline=field.get("inline", True))
    embed.set_footer(text=snap["footer"])
    return embed


def snapshot_view(snap: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for button in snap["buttons"][:25]:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=str(button["label"])[:80],
                url=str(button["url"]),
            )
        )
    return view


async def retire_setup_status_pin(channel: discord.TextChannel) -> None:
    async for msg in channel.history(limit=40):
        if msg.author != channel.guild.me and msg.author != bot.user:
            continue
        for embed in msg.embeds:
            footer = embed.footer.text if embed.footer else ""
            if footer == "fugazy-setup:status":
                try:
                    await msg.delete()
                except discord.HTTPException:
                    pass
                return


async def publish_page_mirror() -> discord.Message | None:
    if not STATUS_CHANNEL_ID or not PUBLIC_IP:
        return None
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if channel is None:
        try:
            fetched = await bot.fetch_channel(STATUS_CHANNEL_ID)
        except discord.HTTPException:
            return None
        channel = fetched
    if not isinstance(channel, discord.TextChannel):
        return None
    snap = page_snapshot()
    embed = snapshot_embed(snap)
    view = snapshot_view(snap)
    state = load_json(MIRROR_STATE_PATH, {})
    message = None
    raw_id = str(state.get("message_id") or "").strip()
    if raw_id.isdigit() and str(state.get("channel_id") or "") == str(channel.id):
        try:
            message = await channel.fetch_message(int(raw_id))
        except discord.HTTPException:
            message = None
    if message is None:
        await retire_setup_status_pin(channel)
        message = await channel.send(embed=embed, view=view)
        save_json(MIRROR_STATE_PATH, {"channel_id": str(channel.id), "message_id": str(message.id)})
        try:
            await message.pin()
        except discord.HTTPException:
            pass
        print(f"page mirror posted #{channel.name} {message.id}")
        return message
    last = str(state.get("snapshot") or "")
    current = json.dumps(
        {"fields": snap["fields"], "buttons": snap["buttons"], "footer": snap["footer"]},
        sort_keys=True,
    )
    if last != current or not message.components:
        await message.edit(embed=embed, view=view)
        save_json(
            MIRROR_STATE_PATH,
            {"channel_id": str(channel.id), "message_id": str(message.id), "snapshot": current},
        )
    return message


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
    return find_pending_item(requests, request_id=request_id, discord_id=discord_id)


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


def livery_embed(item: dict, *, status: str | None = None) -> discord.Embed:
    state = status or item.get("status") or "pending"
    color = {
        "pending": discord.Color.blurple(),
        "approved": discord.Color.green(),
        "denied": discord.Color.red(),
    }.get(state, discord.Color.greyple())
    embed = discord.Embed(
        title=f"Livery reserve ({state})",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Discord", value=f"<@{item['discord_id']}>\n`{item.get('discord_name')}`", inline=True)
    embed.add_field(name="Car", value=f"`{item.get('car')}`", inline=True)
    embed.add_field(name="Color", value=f"`{item.get('skin')}`", inline=True)
    embed.set_footer(text=f"livery {item['id']}")
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


class PersistentLiveryReviewView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="ac_host:livery_approve")
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_livery_button(interaction, approve=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="ac_host:livery_deny")
    async def deny(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await handle_livery_button(interaction, approve=False)


async def handle_livery_button(interaction: discord.Interaction, *, approve: bool) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(
            f"Only `{ADMIN_ROLE}` (or Manage Server) can review livery reserves.",
            ephemeral=True,
        )
        return
    if not interaction.message or not interaction.message.embeds:
        await interaction.response.send_message("Missing request embed.", ephemeral=True)
        return
    footer = interaction.message.embeds[0].footer.text or ""
    request_id = footer.replace("livery ", "").strip()
    if not request_id:
        await interaction.response.send_message("Could not read livery request id.", ephemeral=True)
        return
    await finalize_livery(interaction, request_id, approve=approve)


async def finalize_livery(interaction: discord.Interaction, request_id: str, *, approve: bool) -> None:
    pending = load_pending()
    item = find_pending_item(pending.get("livery_requests") or [], request_id=request_id)
    if not item:
        await interaction.response.send_message("No pending livery request with that id (already handled?).", ephemeral=True)
        return

    guild = interaction.guild
    member = guild.get_member(int(item["discord_id"])) if guild else None
    if member is None and guild:
        try:
            member = await guild.fetch_member(int(item["discord_id"]))
        except discord.HTTPException:
            member = None

    if approve:
        data = load_whitelist()
        holder = find_livery_holder(
            data,
            item["car"],
            item["skin"],
            except_steam=str(item.get("steam_id") or ""),
            except_discord=str(item.get("discord_id") or ""),
        )
        if holder:
            await interaction.response.send_message(
                f"Can't approve — {player_public_name(holder)} already has **{item['car']}** / **{item['skin']}**.",
                ephemeral=True,
            )
            return
        player = player_for_discord(data, str(item["discord_id"])) or find_player(data, steam_id=item.get("steam_id"))
        if not player:
            await interaction.response.send_message("That user is not on the whitelist anymore.", ephemeral=True)
            return
        set_livery(player, item["car"], item["skin"])
        save_whitelist(data)
        item["status"] = "approved"
        item["resolved_at"] = utcnow()
        item["resolved_by"] = str(interaction.user.id)
        save_pending(pending)
        await interaction.response.edit_message(embed=livery_embed(item), view=None)
        if interaction.channel:
            await interaction.channel.send(
                f"<@{item['discord_id']}> reserved **{item['car']}** / **{item['skin']}**. "
                "Applies after the next practice lobby restart."
            )
        if member:
            try:
                await member.send(
                    f"Your livery reserve was **approved**: `{item['car']}` / `{item['skin']}`.\n"
                    "It applies after the next practice lobby restart."
                )
            except discord.HTTPException:
                pass
        return

    item["status"] = "denied"
    item["resolved_at"] = utcnow()
    item["resolved_by"] = str(interaction.user.id)
    save_pending(pending)
    await interaction.response.edit_message(embed=livery_embed(item), view=None)
    if member:
        try:
            await member.send(
                f"Your livery reserve for `{item['car']}` / `{item['skin']}` was **denied**."
            )
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
        self._downtime_prev: float | None = None
        self._countdown_msg: discord.Message | None = None
        self._drill_at: datetime | None = None

    async def setup_hook(self) -> None:
        self.add_view(PersistentReviewView())
        self.add_view(PersistentLiveryReviewView())
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


@tasks.loop(seconds=20)
async def refresh_page_mirror() -> None:
    try:
        await publish_page_mirror()
    except Exception as exc:
        print(f"page mirror refresh failed: {exc}")


@refresh_page_mirror.before_loop
async def wait_for_bot() -> None:
    await bot.wait_until_ready()


async def status_text_channel() -> discord.TextChannel | None:
    if not STATUS_CHANNEL_ID:
        return None
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if channel is None:
        try:
            fetched = await bot.fetch_channel(STATUS_CHANNEL_ID)
        except discord.HTTPException:
            return None
        channel = fetched
    return channel if isinstance(channel, discord.TextChannel) else None


def downtime_remaining() -> float | None:
    drill = bot._drill_at
    if drill is not None:
        delta = (drill - downtime.now_local()).total_seconds()
        if delta < -1:
            bot._drill_at = None
            return downtime.seconds_until_restart()
        return delta
    return downtime.seconds_until_restart()


async def fire_downtime_mark(mark: int) -> None:
    channel = await status_text_channel()
    if channel is None:
        print(f"downtime mark {mark} skipped (no #server-status)")
        return
    whitelist = load_whitelist()
    board = load_json(LEADERBOARD_PATH, {"updated": None, "lobbies": {}})
    online = downtime.online_lines(whitelist, board)
    ids = downtime.mention_ids(whitelist, board) if mark in downtime.MENTION_MARKS else []
    text = downtime.discord_text(mark, online=online)
    users = []
    for snowflake in ids:
        if snowflake.isdigit():
            users.append(discord.Object(id=int(snowflake)))
    mentions = discord.AllowedMentions(everyone=False, roles=False, users=users, replied_user=False)
    try:
        if mark in downtime.EDIT_MARKS and mark < 5 and bot._countdown_msg is not None:
            await bot._countdown_msg.edit(content=text)
            return
        message = await channel.send(text, allowed_mentions=mentions)
        bot._countdown_msg = message if mark == 5 else None
        print(f"downtime discord mark={mark}")
    except discord.HTTPException as exc:
        print(f"downtime discord failed mark={mark}: {exc}")


@tasks.loop(seconds=5)
async def downtime_tick() -> None:
    try:
        remaining = downtime_remaining()
        marks = downtime.crossed_marks(bot._downtime_prev, remaining)
        bot._downtime_prev = remaining
        for mark in marks:
            await fire_downtime_mark(mark)
        if remaining is not None and remaining <= 15:
            downtime_tick.change_interval(seconds=0.2)
        elif remaining is not None and remaining <= 610:
            downtime_tick.change_interval(seconds=1)
        else:
            downtime_tick.change_interval(seconds=5)
    except Exception as exc:
        print(f"downtime tick failed: {exc}")


@downtime_tick.before_loop
async def wait_for_downtime() -> None:
    await bot.wait_until_ready()


@bot.event
async def on_ready() -> None:
    print(f"bot ready as {bot.user} guilds={len(bot.guilds)} review_channel={REVIEW_CHANNEL_ID}")
    print(f"content={CONTENT_PATH} cars={len(car_skins.list_practice_cars(CONTENT_PATH, CATALOG_PATH))}")
    print(f"page mirror channel={STATUS_CHANNEL_ID} ip={PUBLIC_IP or '(unset)'} pages={PAGES_URL}")
    await sync_guild_commands()
    if STATUS_CHANNEL_ID and PUBLIC_IP and not refresh_page_mirror.is_running():
        refresh_page_mirror.start()
    if STATUS_CHANNEL_ID and not downtime_tick.is_running():
        downtime_tick.start()
        nxt = downtime.next_restart()
        print(f"downtime next={nxt.isoformat() if nxt else 'off'}")


@bot.tree.command(name="practice", description="Show practice join links (same as the player page)")
async def practice(interaction: discord.Interaction) -> None:
    snap = page_snapshot()
    await interaction.response.send_message(embed=snapshot_embed(snap), view=snapshot_view(snap), ephemeral=True)


@bot.tree.command(name="downtime-next", description="When the nightly practice recycle fires")
async def downtime_next(interaction: discord.Interaction) -> None:
    nxt = downtime.next_restart()
    remaining = downtime.seconds_until_restart()
    if nxt is None or remaining is None:
        await interaction.response.send_message("Nightly recycle is off (`PRACTICE_RESTART_AT`).", ephemeral=True)
        return
    mins = int(remaining // 60)
    secs = int(remaining % 60)
    await interaction.response.send_message(
        f"Next recycle **{downtime.restart_clock_label(nxt)}** "
        f"({nxt.strftime('%Y-%m-%d %H:%M %Z')}) — in {mins}m {secs}s.\n"
        "Countdown posts in #server-status at 10m / 5m / 1m / 30s / 5s.",
        ephemeral=True,
    )


@bot.tree.command(name="downtime-drill", description="Admin: run the recycle countdown now (Discord only, no kick)")
@app_commands.describe(seconds="Seconds until the fake restart (6–120, default 20)")
async def downtime_drill(interaction: discord.Interaction, seconds: int = 20) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message(f"Need `{ADMIN_ROLE}` or Manage Server.", ephemeral=True)
        return
    seconds = max(6, min(int(seconds), 120))
    bot._drill_at = downtime.now_local() + timedelta(seconds=seconds)
    bot._downtime_prev = float(seconds) + 0.05
    bot._countdown_msg = None
    downtime_tick.change_interval(seconds=0.2)
    await interaction.response.send_message(
        f"Armed a **{seconds}s** countdown in #server-status. "
        "Does **not** restart lobbies. In-game chat still follows the real 3:00 AM clock.",
        ephemeral=True,
    )


@bot.tree.command(name="steam-help", description="How to request access to the AC practice lobbies")
async def steam_help(interaction: discord.Interaction) -> None:
    display = car_skins.load_car_display_names(CATALOG_PATH)
    car_line = " · ".join(
        display.get(folder) or folder for folder in car_skins.PRACTICE_CARS
    )
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
        "After Steam approval: `/livery-set` → pick car → pick color. "
        "An **admin must Approve** before it is reserved. "
        "A reserve holds a **pit slot**, so priority is "
        "**local CVSCC members**, then **SSCLAC members**, then everyone else. "
        "Only **one** preference (a new request replaces the old one after approval). "
        "Each car+color can be held by **one** person.\n"
        "`/livery-show` · `/livery-clear`\n"
        "If you were added by hand, `/livery-set` fails until you `/steam-request` and get approved.\n\n"
        f"**Cars on practice**\n{car_line}\n"
        "We add cars by need. Want another? Post in **#feature-requests**.\n\n"
        "**Tracks** (drop the zip on Content Manager, or join and Download missing content)\n"
        "• [Blackhawk](https://github.com/imkarrer/ac-practice/releases/download/content/slipangle_ggt.zip)\n"
        "• [Road America](https://github.com/imkarrer/ac-practice/releases/download/content/lilski_road_america.zip)\n"
        "• [Gingerman](https://github.com/imkarrer/ac-practice/releases/download/content/gingerman_raceway.zip)"
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
