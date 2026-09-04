"""Steam profile URL parsing (no Discord dependency)."""

from __future__ import annotations

import re

STEAM64 = re.compile(r"^7656119\d{10}$")
PROFILE_URL = re.compile(
    r"^https?://(?:www\.)?steamcommunity\.com/profiles/(7656119\d{10})/?$",
    re.IGNORECASE,
)
VANITY_URL = re.compile(
    r"^https?://(?:www\.)?steamcommunity\.com/id/([A-Za-z0-9_-]{2,32})/?$",
    re.IGNORECASE,
)
STEAM64_XML = re.compile(r"<steamID64>(7656119\d{10})</steamID64>", re.IGNORECASE)


def _strip_url(raw: str) -> str:
    text = raw.strip()
    text = text.split("#", 1)[0]
    text = text.split("?", 1)[0]
    return text.rstrip("/")


def parse_profile(raw: str) -> tuple[str, str] | None:
    """Return (steam_id, canonical_profile_url) for a numeric URL or bare SteamID64."""
    text = _strip_url(raw)
    match = PROFILE_URL.match(text)
    if match:
        steam_id = match.group(1)
        return steam_id, f"https://steamcommunity.com/profiles/{steam_id}"
    if STEAM64.match(text):
        return text, f"https://steamcommunity.com/profiles/{text}"
    found = re.search(r"7656119\d{10}", raw)
    if found and "steamcommunity.com/profiles/" in raw.lower():
        steam_id = found.group(0)
        return steam_id, f"https://steamcommunity.com/profiles/{steam_id}"
    return None


def vanity_slug(raw: str) -> str | None:
    """Custom URL slug from a /id/name link, or None."""
    match = VANITY_URL.match(_strip_url(raw))
    return match.group(1) if match else None


def steam64_from_xml(body: str) -> str | None:
    """Read SteamID64 from Steam's public ?xml=1 profile document."""
    match = STEAM64_XML.search(body)
    return match.group(1) if match else None
