#!/usr/bin/env python3
"""Create Fugazy Discord categories, channels, permissions, and pinned posts.

Uses the bot token over REST only (no gateway), so the live whitelist bot
stays connected. Idempotent: re-running updates topics, overwrites, and pins.

  docker exec -e DISCORD_GUILD_ID=1544532113615749210 ac-host-bot-1 python /tmp/setup_discord.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
DEFAULT_GUILD_ID = "1544532113615749210"
PAGES_URL = os.environ.get("AC_PAGES_URL", "https://simracing.fugazy.dev").rstrip("/") + "/"
ADMIN_ROLE_NAME = os.environ.get("DISCORD_ADMIN_ROLE", "ac-admin")
PRACTICE_ROLE_NAME = os.environ.get("DISCORD_REQUIRED_ROLE", "ac-practice")
MARKER = "fugazy-setup"

# https://discord.com/developers/docs/topics/permissions
CREATE_INSTANT_INVITE = 1 << 0
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
MANAGE_MESSAGES = 1 << 13
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
MANAGE_CHANNELS = 1 << 4
MANAGE_ROLES = 1 << 28
MANAGE_GUILD = 1 << 5
ADMINISTRATOR = 1 << 3
ADD_REACTIONS = 1 << 6
USE_SLASH = 1 << 31
PIN_MESSAGES = 1 << 51

INVITE_PERMS = (
    CREATE_INSTANT_INVITE
    | MANAGE_CHANNELS
    | VIEW_CHANNEL
    | SEND_MESSAGES
    | MANAGE_MESSAGES
    | PIN_MESSAGES
    | EMBED_LINKS
    | ATTACH_FILES
    | READ_MESSAGE_HISTORY
    | ADD_REACTIONS
    | MANAGE_ROLES
    | USE_SLASH
)

TYPE_TEXT = 0
TYPE_CATEGORY = 4
OVERWRITE_ROLE = 0
OVERWRITE_MEMBER = 1
EMBED_COLOR = 0xE11D2E


class DiscordError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} {url}: {body[:500]}")
        self.status = status
        self.body = body


def token() -> str:
    value = os.environ.get("DISCORD_TOKEN", "").strip()
    if not value:
        raise SystemExit("DISCORD_TOKEN is not set")
    return value


def request(method: str, path: str, payload: dict | list | None = None) -> dict | list | None:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {token()}",
            "User-Agent": "FugazyACSetup (ac-host, 1.0)",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < 4:
                retry = 1.0
                try:
                    retry = float(json.loads(body).get("retry_after", 1.0))
                except json.JSONDecodeError:
                    pass
                time.sleep(min(retry + 0.25, 10))
                continue
            raise DiscordError(exc.code, body, path) from exc
    raise DiscordError(429, "rate limited", path)


def has_perm(perms: int, bit: int) -> bool:
    return bool(perms & ADMINISTRATOR) or bool(perms & bit)


def find_named(items: list[dict], name: str, type_: int | None = None) -> dict | None:
    for item in items:
        if item.get("name") != name:
            continue
        if type_ is not None and item.get("type") != type_:
            continue
        return item
    return None


def overwrite(target_id: str, kind: int, allow: int = 0, deny: int = 0) -> dict:
    return {"id": str(target_id), "type": kind, "allow": str(allow), "deny": str(deny)}


def merge_overwrites(existing: list[dict], updates: list[dict]) -> list[dict]:
    by_id = {str(item["id"]): dict(item) for item in existing}
    for item in updates:
        by_id[str(item["id"])] = item
    return list(by_id.values())


def ensure_role(roles: list[dict], name: str) -> dict:
    found = find_named(roles, name)
    if found:
        return found
    created = request("POST", f"/guilds/{os.environ['DISCORD_GUILD_ID']}/roles", {"name": name})
    assert isinstance(created, dict)
    roles.append(created)
    print(f"created role @{name} {created['id']}")
    return created


def ensure_channel(
    channels: list[dict],
    guild_id: str,
    name: str,
    type_: int,
    parent_id: str | None,
    topic: str | None = None,
) -> dict:
    found = find_named(channels, name, type_)
    body: dict = {}
    if found:
        if parent_id is not None and str(found.get("parent_id") or "") != str(parent_id):
            body["parent_id"] = parent_id
        if topic is not None and type_ == TYPE_TEXT and (found.get("topic") or "") != topic:
            body["topic"] = topic
        if body:
            updated = request("PATCH", f"/channels/{found['id']}", body)
            assert isinstance(updated, dict)
            found.update(updated)
            print(f"updated #{name} {found['id']}")
        else:
            print(f"ok #{name} {found['id']}")
        return found
    payload: dict = {"name": name, "type": type_}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if topic and type_ == TYPE_TEXT:
        payload["topic"] = topic
    created = request("POST", f"/guilds/{guild_id}/channels", payload)
    assert isinstance(created, dict)
    channels.append(created)
    print(f"created #{name} {created['id']}")
    return created


def invite_url(code: str) -> str:
    return f"https://discord.gg/{code}"


def pick_permanent_invite(invites: list) -> str | None:
    """Reuse a never-expire / unlimited invite if one already exists."""
    for inv in invites:
        if not isinstance(inv, dict):
            continue
        if int(inv.get("max_age") or 0) != 0:
            continue
        if int(inv.get("max_uses") or 0) != 0:
            continue
        if inv.get("temporary"):
            continue
        code = str(inv.get("code") or "").strip()
        if code:
            return invite_url(code)
    return None


def vanity_invite_url(guild_id: str) -> str | None:
    try:
        data = request("GET", f"/guilds/{guild_id}/vanity-url")
    except DiscordError as exc:
        if exc.status in (403, 404):
            return None
        raise
    if not isinstance(data, dict):
        return None
    code = str(data.get("code") or "").strip()
    return invite_url(code) if code else None


def ensure_permanent_invite(channel: dict, guild_id: str) -> str:
    """Guild vanity if set, else a max_age=0 / max_uses=0 invite on #welcome."""
    vanity = vanity_invite_url(guild_id)
    if vanity:
        print(f"ok vanity invite {vanity}")
        return vanity
    listed = request("GET", f"/channels/{channel['id']}/invites")
    if isinstance(listed, list):
        existing = pick_permanent_invite(listed)
        if existing:
            print(f"ok invite {existing} on #{channel.get('name')}")
            return existing
    created = request(
        "POST",
        f"/channels/{channel['id']}/invites",
        {"max_age": 0, "max_uses": 0, "unique": False, "temporary": False},
    )
    if not isinstance(created, dict) or not created.get("code"):
        raise DiscordError(500, "invite create returned no code", f"/channels/{channel['id']}/invites")
    url = invite_url(str(created["code"]))
    print(f"created invite {url} on #{channel.get('name')}")
    return url


def set_overwrites(channel: dict, updates: list[dict]) -> None:
    merged = merge_overwrites(channel.get("permission_overwrites") or [], updates)
    try:
        updated = request("PATCH", f"/channels/{channel['id']}", {"permission_overwrites": merged})
    except DiscordError as exc:
        print(f"skip overwrites #{channel.get('name')}: {exc.status}")
        return
    assert isinstance(updated, dict)
    channel.update(updated)


def upsert_pin(channel: dict, kind: str, title: str, description: str) -> None:
    messages = request("GET", f"/channels/{channel['id']}/messages?limit=50")
    assert isinstance(messages, list)
    footer = f"{MARKER}:{kind}"
    found = None
    for msg in messages:
        for embed in msg.get("embeds") or []:
            if (embed.get("footer") or {}).get("text") == footer:
                found = msg
                break
        if found:
            break
    embed = {
        "title": title,
        "description": description,
        "color": EMBED_COLOR,
        "footer": {"text": footer},
    }
    if found:
        request("PATCH", f"/channels/{channel['id']}/messages/{found['id']}", {"embeds": [embed]})
        print(f"updated pin {kind} in #{channel['name']}")
        msg_id = found["id"]
    else:
        created = request("POST", f"/channels/{channel['id']}/messages", {"embeds": [embed]})
        assert isinstance(created, dict)
        msg_id = created["id"]
        print(f"posted {kind} in #{channel['name']}")
    try:
        request("PUT", f"/channels/{channel['id']}/pins/{msg_id}")
    except DiscordError as exc:
        if exc.status in (400, 403):
            print(f"skip pin {kind} in #{channel['name']}: {exc.status}")
            return
        raise


def welcome_text() -> str:
    return (
        "Private **Assetto Corsa** practice. Get approved, then jump a lobby.\n"
        f"Player page: {PAGES_URL}\n\n"
        "**1 — Register**\n"
        "Steam → your name → **View my profile** → right-click → **Copy Page URL**.\n"
        "`/id/` or `/profiles/` both work. A SteamID64 is fine too.\n"
        "Then run `/steam-request` and paste that URL. Wait for an admin to **Approve**.\n"
        "You’ll get the `ac-practice` role when you’re on the whitelist.\n\n"
        "**2 — Drive**\n"
        "Install [Content Manager](https://github.com/gro-ove/actools/releases/latest) "
        "and [CSP](https://acstuff.club/patch/) (0.2.11).\n"
        f"Join Discord from [the player page]({PAGES_URL}) (permanent invite), "
        "then the lobby buttons in **#server-status**.\n"
        "After join: **Download missing content**. empty = nobody. A name = someone’s in.\n"
        "Tracks (drop on Content Manager):\n"
        "• [Blackhawk](https://github.com/imkarrer/ac-practice/releases/download/content/slipangle_ggt.zip)\n"
        "• [Road America](https://github.com/imkarrer/ac-practice/releases/download/content/lilski_road_america.zip)\n"
        "• [Gingerman](https://github.com/imkarrer/ac-practice/releases/download/content/gingerman_raceway.zip)\n\n"
        "**3 — Livery (optional)**\n"
        "After Steam approval: `/livery-set` → car → color. An admin has to approve that too.\n"
        "A reserve holds a **pit slot**. Priority: **local CVSCC**, then **SSCLAC**, then everyone else.\n"
        "It does **not** apply mid-session — ask in #now-driving for a lobby restart.\n\n"
        "**Where to post**\n"
        "• #server-status — join buttons and track zip links (same as the player page)\n"
        "• #now-driving — who’s hopping on\n"
        "• #setups-and-help — CM, CSP, black paint, FFB\n"
        "• #bug-reports / #feature-requests — server or car asks\n"
        "• #clips-and-highlights — send it\n\n"
        "`/steam-help` reprints this."
    )


def status_text() -> str:
    return (
        f"**Player page** — {PAGES_URL}\n"
        "Lobbies: **Blackhawk** · **Road America** · **Gingerman**\n"
        "Tracks: [Blackhawk](https://github.com/imkarrer/ac-practice/releases/download/content/slipangle_ggt.zip) · "
        "[Road America](https://github.com/imkarrer/ac-practice/releases/download/content/lilski_road_america.zip) · "
        "[Gingerman](https://github.com/imkarrer/ac-practice/releases/download/content/gingerman_raceway.zip)\n\n"
        "Admins post restarts and downtime here. If a reserved livery just got approved, "
        "the lobby has to restart before that pit is yours.\n\n"
        "Need a car that isn’t on the page? #feature-requests."
    )


def staff_text() -> str:
    return (
        "Players cannot see this category.\n\n"
        f"**#{os.environ.get('REVIEW_HINT', 'ac-whitelist')}** — Steam + livery Approve/Deny "
        "(bot posts here).\n"
        "**#staff** — restarts, bans, entry_list, “who gets the reserved pit”.\n\n"
        "Roles: `ac-admin` (you) · `ac-practice` (approved drivers)."
    )


def main() -> int:
    guild_id = os.environ.get("DISCORD_GUILD_ID", DEFAULT_GUILD_ID).strip()
    os.environ["DISCORD_GUILD_ID"] = guild_id

    me = request("GET", "/users/@me")
    assert isinstance(me, dict)
    bot_id = str(me["id"])
    print(f"bot @{me.get('username')} {bot_id}")

    guilds = request("GET", "/users/@me/guilds")
    assert isinstance(guilds, list)
    guild = next((g for g in guilds if str(g.get("id")) == guild_id), None)
    if guild is None:
        names = ", ".join(f"{g.get('name')} ({g.get('id')})" for g in guilds) or "(none)"
        raise SystemExit(f"bot is not in guild {guild_id}. Guilds: {names}")
    perms = int(guild.get("permissions") or 0)
    print(f"guild {guild.get('name')} {guild_id}")
    if not has_perm(perms, MANAGE_CHANNELS):
        invite = (
            "https://discord.com/oauth2/authorize"
            f"?client_id={bot_id}&scope=bot%20applications.commands&permissions={INVITE_PERMS}"
        )
        print(
            "Bot is missing Manage Channels. Open this invite (same server, extra perms), then re-run:\n"
            f"  {invite}"
        )
        return 2

    roles = request("GET", f"/guilds/{guild_id}/roles")
    assert isinstance(roles, list)
    everyone = next(r for r in roles if str(r["id"]) == guild_id)
    admin = ensure_role(roles, ADMIN_ROLE_NAME)
    practice = ensure_role(roles, PRACTICE_ROLE_NAME)

    channels = request("GET", f"/guilds/{guild_id}/channels")
    assert isinstance(channels, list)

    info = ensure_channel(channels, guild_id, "INFO", TYPE_CATEGORY, None)
    racing = ensure_channel(channels, guild_id, "RACING", TYPE_CATEGORY, None)
    staff_cat = ensure_channel(channels, guild_id, "STAFF", TYPE_CATEGORY, None)

    staff_read = (
        VIEW_CHANNEL
        | SEND_MESSAGES
        | READ_MESSAGE_HISTORY
        | EMBED_LINKS
        | ATTACH_FILES
        | MANAGE_MESSAGES
    )
    announce_staff = staff_read
    announce_everyone = VIEW_CHANNEL | READ_MESSAGE_HISTORY

    planned: list[tuple[dict, str, int, str | None]] = [
        (info, "welcome", TYPE_TEXT, "How to get on the whitelist and join practice."),
        (info, "server-status", TYPE_TEXT, "Which lobby is up, restarts, downtime."),
        (racing, "assetto-corsa", TYPE_TEXT, "General AC chat."),
        (racing, "now-driving", TYPE_TEXT, "Who’s hopping on. Ask here for a lobby restart."),
        (racing, "setups-and-help", TYPE_TEXT, "Content Manager, CSP, black paint, FFB, installs."),
        (racing, "bug-reports", TYPE_TEXT, "Server, track, car, CSP problems."),
        (racing, "feature-requests", TYPE_TEXT, "Cars, tracks, lobby settings."),
        (racing, "clips-and-highlights", TYPE_TEXT, "Clips, screenshots, wrecks."),
        (staff_cat, "ac-whitelist", TYPE_TEXT, "Steam and livery Approve / Deny. Bot posts here."),
        (staff_cat, "staff", TYPE_TEXT, "Restarts, bans, entry_list. Players never see this."),
    ]
    created: dict[str, dict] = {}
    for parent, name, type_, topic in planned:
        created[name] = ensure_channel(channels, guild_id, name, type_, parent["id"], topic)

    set_overwrites(
        created["welcome"],
        [
            overwrite(everyone["id"], OVERWRITE_ROLE, allow=announce_everyone, deny=SEND_MESSAGES),
            overwrite(admin["id"], OVERWRITE_ROLE, allow=announce_staff),
            overwrite(bot_id, OVERWRITE_MEMBER, allow=announce_staff | CREATE_INSTANT_INVITE),
        ],
    )
    set_overwrites(
        created["server-status"],
        [
            overwrite(everyone["id"], OVERWRITE_ROLE, allow=announce_everyone, deny=SEND_MESSAGES),
            overwrite(admin["id"], OVERWRITE_ROLE, allow=announce_staff),
            overwrite(bot_id, OVERWRITE_MEMBER, allow=announce_staff),
        ],
    )
    for name in ("ac-whitelist", "staff"):
        set_overwrites(
            created[name],
            [
                overwrite(everyone["id"], OVERWRITE_ROLE, deny=VIEW_CHANNEL),
                overwrite(practice["id"], OVERWRITE_ROLE, deny=VIEW_CHANNEL),
                overwrite(admin["id"], OVERWRITE_ROLE, allow=staff_read),
                overwrite(bot_id, OVERWRITE_MEMBER, allow=staff_read),
            ],
        )
    print("permissions set")

    # Discord allows only one parent_id change per bulk PATCH. Parents are
    # already set in ensure_channel; this pass is position-only.
    positions = [
        {"id": info["id"], "position": 0},
        {"id": racing["id"], "position": 1},
        {"id": staff_cat["id"], "position": 2},
        {"id": created["welcome"]["id"], "position": 0},
        {"id": created["server-status"]["id"], "position": 1},
        {"id": created["assetto-corsa"]["id"], "position": 0},
        {"id": created["now-driving"]["id"], "position": 1},
        {"id": created["setups-and-help"]["id"], "position": 2},
        {"id": created["bug-reports"]["id"], "position": 3},
        {"id": created["feature-requests"]["id"], "position": 4},
        {"id": created["clips-and-highlights"]["id"], "position": 5},
        {"id": created["ac-whitelist"]["id"], "position": 0},
        {"id": created["staff"]["id"], "position": 1},
    ]
    request("PATCH", f"/guilds/{guild_id}/channels", positions)

    invite = ""
    try:
        invite = ensure_permanent_invite(created["welcome"], guild_id)
    except DiscordError as exc:
        extra = (
            "https://discord.com/oauth2/authorize"
            f"?client_id={bot_id}&scope=bot%20applications.commands&permissions={INVITE_PERMS}"
        )
        print(f"skip permanent invite ({exc.status}). Grant Create Instant Invite, then re-run:\n  {extra}")

    upsert_pin(created["welcome"], "welcome", "Welcome to Fugazy Sim Racing", welcome_text())
    upsert_pin(created["staff"], "staff", "Staff", staff_text())
    # #server-status is owned by the live page-mirror bot (join buttons).

    if has_perm(perms, MANAGE_GUILD):
        try:
            request("PATCH", f"/guilds/{guild_id}", {"system_channel_id": created["welcome"]["id"]})
        except DiscordError as exc:
            print(f"skip system channel: {exc}")
        try:
            request(
                "PATCH",
                f"/guilds/{guild_id}/welcome-screen",
                {
                    "enabled": True,
                    "description": "Private Assetto Corsa practice. Get approved, then jump a lobby.",
                    "welcome_channels": [
                        {
                            "channel_id": created["welcome"]["id"],
                            "description": "How to register and join",
                            "emoji_name": "🏁",
                        },
                        {
                            "channel_id": created["server-status"]["id"],
                            "description": "Lobby status and restarts",
                            "emoji_name": "🟢",
                        },
                        {
                            "channel_id": created["now-driving"]["id"],
                            "description": "Who is hopping on",
                            "emoji_name": "🏎️",
                        },
                    ],
                },
            )
            print("welcome screen updated")
        except DiscordError as exc:
            print(f"skip welcome screen (enable Community in Server Settings if you want it): {exc.status}")

    report = {
        "guild_id": guild_id,
        "welcome": created["welcome"]["id"],
        "server_status": created["server-status"]["id"],
        "assetto_corsa": created["assetto-corsa"]["id"],
        "now_driving": created["now-driving"]["id"],
        "setups_and_help": created["setups-and-help"]["id"],
        "bug_reports": created["bug-reports"]["id"],
        "feature_requests": created["feature-requests"]["id"],
        "clips_and_highlights": created["clips-and-highlights"]["id"],
        "ac_whitelist": created["ac-whitelist"]["id"],
        "staff": created["staff"]["id"],
        "invite": invite,
    }
    print("REPORT " + json.dumps(report))
    print(f"DISCORD_REVIEW_CHANNEL_ID={report['ac_whitelist']}")
    print(f"DISCORD_CHANNEL_URL=https://discord.com/channels/{guild_id}/{report['welcome']}")
    print(
        "DISCORD_FEATURE_REQUESTS_URL="
        f"https://discord.com/channels/{guild_id}/{report['feature_requests']}"
    )
    if invite:
        print(f"DISCORD_INVITE_URL={invite}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DiscordError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
