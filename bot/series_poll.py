"""Series #1 community poll — PM review draft."""

from __future__ import annotations

import os

import discord

from series_poll_content import FREEFORM, INTRO, POLLS, PM_ROLE_DEFAULT, POLL_DURATION_HOURS

__all__ = [
    "FREEFORM",
    "INTRO",
    "POLLS",
    "PM_ROLE_DEFAULT",
    "POLL_DURATION_HOURS",
    "make_poll",
    "members_with_role",
    "send_pm_review",
]


def make_poll(question: str, answers: list[str]) -> discord.Poll:
    return discord.Poll(
        question=question[:300],
        answers=[discord.PollAnswer(text=text[:55]) for text in answers[:10]],
        duration=POLL_DURATION_HOURS,
        allow_multiselect=False,
    )


async def members_with_role(guild: discord.Guild, role: discord.Role) -> list[discord.Member]:
    """Resolve role members without requiring Server Members Intent when possible."""
    live = [m for m in role.members if not m.bot]
    if live:
        return live

    explicit = os.environ.get("DISCORD_PM_USER_IDS", "").strip()
    if explicit:
        out: list[discord.Member] = []
        for raw in explicit.split(","):
            raw = raw.strip()
            if not raw.isdigit():
                continue
            try:
                member = await guild.fetch_member(int(raw))
            except discord.HTTPException:
                continue
            if role in member.roles and not member.bot:
                out.append(member)
        if out:
            return out

    found: dict[int, discord.Member] = {}
    queries = os.environ.get(
        "DISCORD_PM_SEARCH_QUERIES",
        "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t,u,v,w,x,y,z,0,1,2,3,4,5,6,7,8,9",
    ).split(",")
    for query in queries:
        q = query.strip()
        if not q:
            continue
        try:
            results = await guild.search_members(query=q, limit=100)
        except discord.HTTPException:
            continue
        for member in results:
            if role in member.roles and not member.bot:
                found[member.id] = member
    return list(found.values())


async def send_pm_review(
    *,
    guild: discord.Guild,
    pm_role_name: str,
    sender: discord.abc.Messageable,
) -> tuple[int, list[str]]:
    """DM poll package to every member with the PM role. Returns (sent_count, errors)."""
    role = discord.utils.get(guild.roles, name=pm_role_name)
    if role is None:
        raise RuntimeError(f"role {pm_role_name!r} not found on {guild.name}")
    members = await members_with_role(guild, role)
    if not members:
        raise RuntimeError(
            f"no members in @{pm_role_name}. Set DISCORD_PM_USER_IDS or enable Server Members Intent."
        )
    sent = 0
    errors: list[str] = []
    for member in members:
        try:
            dm = await member.create_dm()
            await dm.send(INTRO)
            for question, answers in POLLS:
                await dm.send(poll=make_poll(question, answers))
            await dm.send(FREEFORM)
            sent += 1
        except discord.HTTPException as exc:
            errors.append(f"{member}: {exc}")
    summary = (
        f"Sent Series #1 PM review to **{sent}** member(s) with `@{pm_role_name}`."
        + (f" Failed: {', '.join(errors)}" if errors else "")
    )
    await sender.send(summary)
    return sent, errors
