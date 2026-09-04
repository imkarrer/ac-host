"""Whitelist lookup and one-car livery preference (no Discord dependency)."""

from __future__ import annotations

from datetime import datetime, timezone

NOT_BOT_REGISTERED = (
    "You're not registered with the bot yet.\n"
    "Run `/steam-request` with your Steam profile URL "
    "(`https://steamcommunity.com/profiles/7656…`), then wait for an admin to **Approve**.\n"
    "A manual server entry is not enough — register first, then set your car/color."
)


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def find_player(
    data: dict,
    *,
    discord_id: str | None = None,
    steam_id: str | None = None,
) -> dict | None:
    for player in data.get("players") or []:
        # Ignore placeholder discord_id "0" from manual whitelist rows.
        if discord_id and discord_id != "0" and str(player.get("discord_id") or "") == discord_id:
            return player
        if steam_id and str(player.get("steam_id") or "") == steam_id:
            return player
    return None


def is_bot_registered(player: dict | None) -> bool:
    """True only for an enabled row written by /steam-request → Approve."""
    if not player:
        return False
    if not player.get("enabled"):
        return False
    discord_id = str(player.get("discord_id") or "")
    return bool(discord_id) and discord_id != "0"


def player_for_discord(data: dict, discord_id: str) -> dict | None:
    """Whitelist row for this Discord user if they registered via the bot."""
    if not discord_id or discord_id == "0":
        return None
    player = find_player(data, discord_id=str(discord_id))
    return player if is_bot_registered(player) else None


def livery_matches(player: dict, car: str, skin: str) -> bool:
    livery = player.get("livery")
    if not isinstance(livery, dict):
        return False
    return str(livery.get("car") or "") == car and str(livery.get("skin") or "") == skin


def find_livery_holder(
    data: dict,
    car: str,
    skin: str,
    *,
    except_steam: str | None = None,
    except_discord: str | None = None,
) -> dict | None:
    """Enabled player who already reserved this car+color, if any."""
    for player in data.get("players") or []:
        if not player.get("enabled", True):
            continue
        steam = str(player.get("steam_id") or "")
        discord_id = str(player.get("discord_id") or "")
        if except_steam and steam == except_steam:
            continue
        if except_discord and except_discord != "0" and discord_id == except_discord:
            continue
        if livery_matches(player, car, skin):
            return player
    return None


def player_public_name(player: dict) -> str:
    discord_id = str(player.get("discord_id") or "")
    if discord_id and discord_id != "0":
        return f"<@{discord_id}>"
    name = str(player.get("discord_name") or "").strip()
    if name:
        return name
    return f"`{player.get('steam_id')}`"


def set_livery(player: dict, car: str, skin: str) -> None:
    player["livery"] = {"car": car, "skin": skin, "updated_at": utcnow()}


def clear_livery(player: dict) -> bool:
    if "livery" not in player:
        return False
    del player["livery"]
    return True


def format_livery(player: dict) -> str:
    livery = player.get("livery")
    if not isinstance(livery, dict) or not livery.get("car"):
        return "none (server default when you join)"
    return f"`{livery.get('car')}` / `{livery.get('skin')}`"


def find_pending_item(requests: list[dict], *, request_id: str | None = None, discord_id: str | None = None) -> dict | None:
    for item in requests:
        if item.get("status") != "pending":
            continue
        if request_id and item.get("id") == request_id:
            return item
        if discord_id and item.get("discord_id") == discord_id:
            return item
    return None


def find_pending_livery_combo(
    requests: list[dict],
    car: str,
    skin: str,
    *,
    except_discord: str | None = None,
) -> dict | None:
    """Another pending request already claiming this car+color."""
    for item in requests:
        if item.get("status") != "pending":
            continue
        if except_discord and item.get("discord_id") == except_discord:
            continue
        if item.get("car") == car and item.get("skin") == skin:
            return item
    return None
