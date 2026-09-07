"""Discord slash commands for series lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord import app_commands

if TYPE_CHECKING:
    from bot import LobbyBot

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE, _HERE.parent / "shared"):
    if (_candidate / "series_lib.py").is_file() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
        break

import car_skins  # noqa: E402
import series_lib  # noqa: E402
from series_poll import PM_ROLE_DEFAULT, send_pm_review  # noqa: E402

try:
    import buildkite_trigger  # noqa: E402
except ImportError:
    buildkite_trigger = None  # type: ignore[assignment]

SERIES_CATEGORY_ACTIVE = "SERIES — Active"
SERIES_CATEGORY_ARCHIVE = "SERIES — Archive"
VIEW_CHANNEL = discord.Permissions(view_channel=True)
READ_HISTORY = discord.Permissions(view_channel=True, read_message_history=True)
SEND_MESSAGES = discord.Permissions(view_channel=True, send_messages=True, read_message_history=True)


def _state_root() -> Path:
    wl = Path(os.environ.get("WHITELIST_PATH", "/data/whitelist.json"))
    explicit = os.environ.get("AC_STATE", "").strip()
    raw = Path(explicit) if explicit else wl.parent
    return series_lib.resolve_state_root(raw)


def _repo() -> Path:
    return Path(os.environ.get("AC_REPO", "/repo"))


def _build_content() -> Path:
    return Path(os.environ.get("AC_BUILD", "/build")) / "content"


def _serve_content() -> Path:
    return Path(os.environ.get("AC_SERVE_CONTENT", "/serve"))


def run_series_pack(series_id: str) -> tuple[int, str]:
    """Build numbered skins on this host. The workstation is not involved."""
    script = _repo() / "scripts" / "generate_series_liveries.py"
    if not script.is_file():
        return 2, f"missing {script} — is /repo mounted?"
    cmd = [
        sys.executable,
        str(script),
        "--series",
        series_id,
        "--state",
        str(_state_root()),
        "--catalog",
        str(_catalog()),
        "--content",
        str(_build_content()),
        "--serve-content",
        str(_serve_content()),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return 2, "livery generation timed out after 15 minutes"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _queue_series_pack(series_id: str, round_id: str) -> str:
    """Start the Buildkite race-pack job. Empty string → caller bakes locally."""
    if buildkite_trigger is None or not buildkite_trigger.configured():
        return ""
    try:
        build = buildkite_trigger.trigger(
            message=f"Race pack {series_id} {round_id}",
            env={"SERIES_ID": series_id, "ROUND_ID": round_id},
        )
    except Exception as exc:
        print(f"buildkite pack trigger failed: {exc}")
        return ""
    return str(build.get("web_url") or build.get("url") or "queued")


def _catalog() -> Path:
    return Path(os.environ.get("AC_CATALOG", "/catalog"))


def _content() -> Path:
    return Path(os.environ.get("AC_CONTENT", "/content"))


def _pages_url() -> str:
    return os.environ.get("AC_PAGES_URL", "https://simracing.fugazy.dev").rstrip("/")


def _public_ip() -> str:
    return os.environ.get("AC_PUBLIC_IP", "").strip()


def _join_url(http_port: int) -> str:
    ip = _public_ip()
    if not ip:
        return ""
    return f"https://acstuff.ru/s/q:race/online/join?ip={ip}&httpPort={http_port}"


def _series_ids(catalog: Path) -> list[str]:
    return series_lib.list_series_ids(catalog, _state_root())


def _car_choices() -> list[tuple[str, str]]:
    cars = car_skins.list_practice_cars(_content(), _catalog())
    if cars:
        return cars
    display = car_skins.load_car_display_names(_catalog())
    return [(folder, display.get(folder) or folder) for folder in car_skins.PRACTICE_CARS]


async def series_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    choices = []
    for sid in _series_ids(_catalog()):
        label = sid
        if cur and cur not in sid.lower():
            continue
        choices.append(app_commands.Choice(name=label[:100], value=sid))
        if len(choices) >= 25:
            break
    return choices


async def car_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    choices: list[app_commands.Choice[str]] = []
    for folder, label in _car_choices():
        display = label if label == folder else f"{label} ({folder})"
        if cur and cur not in display.lower() and cur not in folder.lower():
            continue
        choices.append(app_commands.Choice(name=display[:100], value=folder))
        if len(choices) >= 25:
            break
    return choices


async def track_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    cur = current.lower()
    choices: list[app_commands.Choice[str]] = []
    for tid, label in series_lib.list_tracks(_catalog()):
        display = label if label == tid else f"{label} ({tid})"
        if cur and cur not in display.lower() and cur not in tid.lower():
            continue
        choices.append(app_commands.Choice(name=display[:100], value=tid))
        if len(choices) >= 25:
            break
    return choices


async def series_skin_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    series_id = ""
    if interaction.namespace:
        series_id = str(getattr(interaction.namespace, "series_id", "") or "")
    if not series_id:
        return []
    try:
        spec = series_lib.load_catalog(_catalog(), series_id, _state_root())
    except (FileNotFoundError, ValueError):
        return []
    car = str(spec.get("car") or "")
    if not car:
        return []
    cur = current.lower()
    choices: list[app_commands.Choice[str]] = []
    for skin_id, label in car_skins.list_signup_skins(_content(), car):
        display = label if label == skin_id else f"{label} ({skin_id})"
        if cur and cur not in display.lower() and cur not in skin_id.lower():
            continue
        choices.append(app_commands.Choice(name=display[:100], value=skin_id))
        if len(choices) >= 25:
            break
    return choices


async def round_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    series_id = ""
    if interaction.namespace:
        series_id = str(getattr(interaction.namespace, "series_id", "") or "")
    if not series_id:
        return []
    try:
        spec = series_lib.load_catalog(_catalog(), series_id, _state_root())
    except (FileNotFoundError, ValueError):
        return []
    cur = current.lower()
    choices = []
    for rnd in spec.get("rounds") or []:
        rid = str(rnd.get("id") or "")
        if not rid:
            continue
        if cur and cur not in rid.lower():
            continue
        choices.append(app_commands.Choice(name=rid[:100], value=rid))
        if len(choices) >= 25:
            break
    return choices


def register_series_commands(
    bot: LobbyBot,
    *,
    is_admin,
    is_whitelisted,
    player_for_discord,
    player_public_name,
    required_role: str,
    admin_role: str,
) -> None:
    state_root = _state_root()
    catalog = _catalog()

    async def ensure_series_role(guild: discord.Guild, role_name: str) -> discord.Role:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            return role
        return await guild.create_role(name=role_name, reason="series-init")

    async def ensure_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
        for ch in guild.categories:
            if ch.name == name:
                return ch
        return await guild.create_category(name)

    def refresh_page(series_id: str, join_url: str = "") -> None:
        series_lib.write_page_payload(
            state_root,
            catalog,
            series_id,
            pages_url=_pages_url(),
            join_url=join_url,
        )

    admin = app_commands.Group(
        name="admin",
        description=f"Series ops — {admin_role} only",
    )
    practice = app_commands.Group(
        name="ac-practice",
        description="Series commands for approved drivers",
    )

    @admin.command(name="poll-pm", description="DM Series #1 poll to product-manager role for review")
    async def series_poll_pm(interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}` or Manage Server.", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("Run in the server.", ephemeral=True)
            return
        pm_role = os.environ.get("DISCORD_PM_ROLE", PM_ROLE_DEFAULT)
        await interaction.response.defer(ephemeral=True)
        try:
            sent, errors = await send_pm_review(
                guild=interaction.guild,
                pm_role_name=pm_role,
                sender=interaction.followup,
            )
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        note = f"Sent to {sent} PM(s)."
        if errors:
            note += f" Errors: {'; '.join(errors[:3])}"
        await interaction.followup.send(note, ephemeral=True)

    async def wire_discord(guild: discord.Guild, spec: dict) -> discord.Role:
        series_id = str(spec.get("id") or "")
        role_name = str(spec.get("discordRole") or series_id)
        role = await ensure_series_role(guild, role_name)
        active = await ensure_category(guild, SERIES_CATEGORY_ACTIVE)
        archive = await ensure_category(guild, SERIES_CATEGORY_ARCHIVE)
        meta_path = state_root / "series" / series_id / "meta.json"
        meta = series_lib.load_json(meta_path, {})
        meta["discord_role"] = role_name
        meta["discord_category_active"] = str(active.id)
        meta["discord_category_archive"] = str(archive.id)
        series_lib.save_json(meta_path, meta)
        return role

    @admin.command(name="init", description="Create a series: name, car, optional first track")
    @app_commands.describe(
        name="Display name, e.g. Fugazy Series #1",
        car="Season car (autocomplete)",
        series_id="Optional slug; default is generated from the name",
        track="Optional first calendar track",
        when="Optional first-round date, e.g. 2026-09-12 19:00",
    )
    @app_commands.autocomplete(car=car_autocomplete, track=track_autocomplete)
    async def series_init(
        interaction: discord.Interaction,
        name: str,
        car: str,
        series_id: str = "",
        track: str = "",
        when: str = "",
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("Run in the server.", ephemeral=True)
            return
        allowed = {folder for folder, _ in _car_choices()}
        if car not in allowed:
            await interaction.response.send_message(
                f"Unknown car `{car}`. Pick from the autocomplete list.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        created = True
        try:
            scheduled = series_lib.parse_scheduled(when) if when else None
            spec = series_lib.create_series(
                state_root,
                catalog,
                name=name,
                car=car,
                series_id=series_id,
                track=track,
                scheduled=scheduled,
            )
            role = await wire_discord(interaction.guild, spec)
            refresh_page(str(spec["id"]))
        except ValueError as exc:
            if "already exists" not in str(exc):
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            created = False
            try:
                sid = series_lib.validate_series_id(series_id or series_lib.slug_series_id(name))
                spec = series_lib.load_catalog(catalog, sid, state_root)
                role = await wire_discord(interaction.guild, spec)
            except (FileNotFoundError, ValueError) as inner:
                await interaction.followup.send(str(inner), ephemeral=True)
                return
        except FileNotFoundError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        sid = str(spec["id"])
        rounds = spec.get("rounds") or []
        cal = ", ".join(f"{r.get('id')} {r.get('track')}" for r in rounds) or "none yet — `/admin add-round`"
        verb = "Created" if created else "Already initialized"
        await interaction.followup.send(
            f"{verb} **{spec.get('displayName') or sid}** (`{sid}`). "
            f"Car `{spec.get('car')}`. Role `{role.name}`. Calendar: {cal}.",
            ephemeral=True,
        )

    @admin.command(name="add-round", description="Append a track to a series calendar")
    @app_commands.describe(
        series_id="Series to extend",
        track="Track (autocomplete)",
        when="Optional date, e.g. 2026-09-12 19:00",
        pilot="Non-points pilot weekend",
    )
    @app_commands.autocomplete(series_id=series_autocomplete, track=track_autocomplete)
    async def series_add_round(
        interaction: discord.Interaction,
        series_id: str,
        track: str,
        when: str = "",
        pilot: bool = False,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            scheduled = series_lib.parse_scheduled(when) if when else None
            row = series_lib.add_round(
                state_root,
                catalog,
                series_id,
                track=track,
                scheduled=scheduled,
                pilot=pilot,
            )
            refresh_page(series_id)
        except (FileNotFoundError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        when_note = f" @ {row['scheduled']}" if row.get("scheduled") else ""
        pilot_note = " (pilot)" if row.get("pilot") else ""
        await interaction.followup.send(
            f"Added `{row['id']}` {row['track']}{when_note}{pilot_note} to `{series_id}`. "
            f"Open it with `/admin round-open`.",
            ephemeral=True,
        )

    @practice.command(name="info", description="Series calendar, signups, and page link")
    @app_commands.autocomplete(series_id=series_autocomplete)
    async def series_info(interaction: discord.Interaction, series_id: str) -> None:
        try:
            spec = series_lib.load_catalog(catalog, series_id, state_root)
            signups = series_lib.load_signups(state_root, series_id)
            rounds = series_lib.load_all_rounds(state_root, series_id)
        except (FileNotFoundError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        embed = discord.Embed(
            title=spec.get("displayName") or series_id,
            description=f"[Standings page]({_pages_url()}/series.html#{series_id})",
            color=discord.Color.red(),
        )
        embed.add_field(name="Signups", value=str(len(signups.get("drivers") or [])), inline=True)
        embed.add_field(name="Car", value=str(spec.get("car") or "—"), inline=True)
        embed.add_field(name="Quali mode", value=str(spec.get("qualMode") or "live"), inline=True)
        cal_lines = []
        for rnd in spec.get("rounds") or []:
            rid = rnd.get("id")
            live = next((r for r in rounds if r.get("id") == rid), {})
            status = live.get("status") or "scheduled"
            pilot = " (pilot)" if rnd.get("pilot") else ""
            cal_lines.append(f"`{rid}` {rnd.get('track')} — **{status}**{pilot}")
        embed.add_field(name="Calendar", value="\n".join(cal_lines)[:1024] or "—", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @practice.command(name="signup", description="Register for a championship")
    @app_commands.describe(series_id="Series id", skin="Optional factory paint color")
    @app_commands.autocomplete(series_id=series_autocomplete, skin=series_skin_autocomplete)
    async def series_signup(interaction: discord.Interaction, series_id: str, skin: str = "") -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Run in the server.", ephemeral=True)
            return
        wl_path = Path(os.environ.get("WHITELIST_PATH", "/data/whitelist.json"))
        wl = series_lib.load_json(wl_path, {"players": []})
        player = player_for_discord(wl, str(interaction.user.id))
        if not player or not player.get("enabled"):
            await interaction.response.send_message("Register with `/intake` first.", ephemeral=True)
            return
        try:
            spec = series_lib.load_catalog(catalog, series_id, state_root)
            car = str(spec.get("car") or "")
            number = str(player.get("number") or "").strip()
            if not number:
                await interaction.response.send_message(
                    "Reserve a race number first: `/intake` with a number 1–999.",
                    ephemeral=True,
                )
                return
            skin = skin.strip()
            if skin:
                allowed = {folder for folder, _ in car_skins.list_signup_skins(_content(), car)}
                if skin not in allowed:
                    await interaction.response.send_message(
                        f"Unknown color `{skin}`. Pick from the autocomplete list.",
                        ephemeral=True,
                    )
                    return
            driver = series_lib.signup_driver(
                state_root,
                catalog,
                series_id,
                steam_id=str(player.get("steam_id") or ""),
                discord_id=str(interaction.user.id),
                name=player_public_name(player),
                skin=skin,
                number=number,
            )
            refresh_page(series_id)
        except (FileNotFoundError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        role_name = str(spec.get("discordRole") or series_id)
        role = discord.utils.get(interaction.guild.roles, name=role_name) if interaction.guild else None
        if role and interaction.guild and interaction.guild.me.top_role > role:
            try:
                await interaction.user.add_roles(role, reason=f"series-signup {series_id}")
            except discord.HTTPException:
                pass
        skin_note = ""
        if driver.get("skin"):
            label = dict(car_skins.list_signup_skins(_content(), car)).get(driver["skin"], driver["skin"])
            skin_note = f" — **{label}**"
        await interaction.response.send_message(
            f"Signed up for **{spec.get('displayName') or series_id}**{skin_note} — **#{number}**. "
            f"Use `/ac-practice info` for the calendar.",
            ephemeral=True,
        )

    @practice.command(name="withdraw", description="Leave a championship before your grid is locked")
    @app_commands.autocomplete(series_id=series_autocomplete)
    async def series_withdraw(interaction: discord.Interaction, series_id: str) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Run in the server.", ephemeral=True)
            return
        rounds = series_lib.load_all_rounds(state_root, series_id)
        locked = any(str(r.get("status") or "") in ("grid_locked", "racing", "provisional", "final", "archived") for r in rounds)
        signups = series_lib.load_signups(state_root, series_id)
        me = series_lib.find_signup(signups, discord_id=str(interaction.user.id))
        if not me:
            await interaction.response.send_message("You are not signed up.", ephemeral=True)
            return
        if locked:
            await interaction.response.send_message(
                "Cannot withdraw — a round grid is already locked or racing.",
                ephemeral=True,
            )
            return
        if not series_lib.withdraw_driver(state_root, series_id, discord_id=str(interaction.user.id)):
            await interaction.response.send_message("Withdraw failed.", ephemeral=True)
            return
        refresh_page(series_id)
        await interaction.response.send_message(f"Withdrew from `{series_id}`.", ephemeral=True)

    @practice.command(name="signups", description="List registered drivers")
    @app_commands.autocomplete(series_id=series_autocomplete)
    async def series_signups(interaction: discord.Interaction, series_id: str) -> None:
        try:
            signups = series_lib.load_signups(state_root, series_id)
        except FileNotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        drivers = signups.get("drivers") or []
        if not drivers:
            await interaction.response.send_message("No signups yet.", ephemeral=True)
            return
        lines = [
            f"{i}. #{d.get('number') or '—'} {d.get('name') or d.get('steam_id')}"
            for i, d in enumerate(drivers, 1)
        ]
        await interaction.response.send_message("\n".join(lines[:40]), ephemeral=True)

    @admin.command(name="round-open", description="Open a round channel")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def round_open(interaction: discord.Interaction, series_id: str, round_id: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("Run in the server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            spec = series_lib.load_catalog(catalog, series_id, state_root)
            rnd_spec = series_lib.catalog_round(spec, round_id)
            rnd = series_lib.load_round(state_root, series_id, round_id)
            track = series_lib.load_track_catalog(catalog, str(rnd_spec.get("track") or ""))
            meta = series_lib.load_json(state_root / "series" / series_id / "meta.json", {})
            cat_id = meta.get("discord_category_active")
            parent = interaction.guild.get_channel(int(cat_id)) if str(cat_id or "").isdigit() else None
            if parent is None:
                parent = await ensure_category(interaction.guild, SERIES_CATEGORY_ACTIVE)
            slug = str(track.get("id") or rnd_spec.get("track") or "track")
            channel_name = f"{series_id}-{round_id}-{slug}"[:100]
            channel = await interaction.guild.create_text_channel(
                channel_name,
                category=parent if isinstance(parent, discord.CategoryChannel) else None,
                topic=f"{spec.get('displayName')} — {round_id}",
            )
            guild_id = interaction.guild.id
            rnd["discord_channel_id"] = str(channel.id)
            rnd["discord_channel_url"] = f"https://discord.com/channels/{guild_id}/{channel.id}"
            series_lib.set_round_status(rnd, "open")
            series_lib.save_round(state_root, series_id, round_id, rnd)
            refresh_page(series_id)
            pilot = " **NON-POINTS PILOT**" if rnd_spec.get("pilot") else ""
            pin = (
                f"**{spec.get('displayName')} — {round_id.upper()}**{pilot}\n"
                f"Track: **{track.get('displayName') or slug}**\n"
                f"Page: {_pages_url()}/series.html#{round_id}\n"
                f"Signup: `/ac-practice signup {series_id}`\n"
                f"Quali closes → entry list locks. Miss quali = back marker."
            )
            msg = await channel.send(pin)
            try:
                await msg.pin()
            except discord.HTTPException:
                pass
        except (FileNotFoundError, ValueError, KeyError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(f"Opened {channel.mention}.", ephemeral=True)

    @practice.command(name="round-info", description="Round status, grid, and links")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def round_info(interaction: discord.Interaction, series_id: str, round_id: str) -> None:
        try:
            rnd = series_lib.load_round(state_root, series_id, round_id)
        except FileNotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        grid = rnd.get("grid") or []
        lines = [f"Status: **{rnd.get('status')}**"]
        if rnd.get("discord_channel_url"):
            lines.append(f"Channel: {rnd['discord_channel_url']}")
        if rnd.get("join_url"):
            lines.append(f"Join: {rnd['join_url']}")
        if grid:
            lines.append("Grid:")
            for row in grid[:20]:
                qt = row.get("qual_time_ms")
                t = f" — {qt}ms" if qt else " — no quali"
                lines.append(f"P{row.get('pos')} {row.get('name')}{t}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @admin.command(name="quali-close", description="Lock grid from quali laps (missed quali → back)")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def quali_close(interaction: discord.Interaction, series_id: str, round_id: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            grid = series_lib.lock_grid_from_quali(state_root, catalog, series_id, round_id)
            rnd = series_lib.load_round(state_root, series_id, round_id)
            refresh_page(series_id)
        except (FileNotFoundError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        lines = [f"P{g['pos']} {g['name']}" + ("" if g.get("qual_time_ms") else " *(no quali)*") for g in grid]
        await interaction.followup.send(
            "Grid locked. Building numbered liveries on the race server…\n" + "\n".join(lines[:25]),
            ephemeral=True,
        )
        queued = await asyncio.get_event_loop().run_in_executor(None, _queue_series_pack, series_id, round_id)
        if queued:
            pack_note = f"Race pack queued on Buildkite.\n{queued}"
            code = 0
        else:
            code, log = await asyncio.get_event_loop().run_in_executor(None, run_series_pack, series_id)
            tail = "\n".join(log.splitlines()[-12:]) if log else "(no output)"
            if code == 0:
                pack_note = f"Race pack ready.\n```\n{tail}\n```"
            else:
                pack_note = f"Race pack **failed** (exit {code}). Grid is still locked.\n```\n{tail}\n```"
        await interaction.followup.send(pack_note[:1900], ephemeral=True)
        ch_id = str(rnd.get("discord_channel_id") or "")
        if interaction.guild and ch_id.isdigit():
            ch = interaction.guild.get_channel(int(ch_id))
            if isinstance(ch, discord.TextChannel):
                if queued:
                    await ch.send(
                        "**Grid locked** — numbered liveries are baking on Buildkite. "
                        "See `/ac-practice grid-show`."
                    )
                elif code == 0:
                    await ch.send("**Grid locked** — numbered liveries are on the race server. See `/ac-practice grid-show`.")
                else:
                    await ch.send("**Grid locked** — livery generation failed; skins were not published.")

    @practice.command(name="grid-show", description="Show the starting grid")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def grid_show(interaction: discord.Interaction, series_id: str, round_id: str) -> None:
        try:
            rnd = series_lib.load_round(state_root, series_id, round_id)
        except FileNotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        grid = rnd.get("grid") or []
        if not grid:
            await interaction.response.send_message("Grid not set yet.", ephemeral=True)
            return
        lines = []
        for row in grid:
            ms = row.get("qual_time_ms")
            qual = ""
            if ms is not None:
                qual = f" — {int(ms) // 60000}:{(int(ms) % 60000) // 1000:02d}.{int(ms) % 1000:03d}"
            lines.append(f"P{row.get('pos')} {row.get('name')}{qual}")
        await interaction.response.send_message("```\n" + "\n".join(lines) + "\n```", ephemeral=True)

    @admin.command(name="race-start", description="Mark round live and post join link")
    @app_commands.describe(http_port="Race server HTTP port (from acctl start-race)")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def race_start(
        interaction: discord.Interaction,
        series_id: str,
        round_id: str,
        http_port: int,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        join = _join_url(http_port)
        try:
            spec = series_lib.load_catalog(catalog, series_id, state_root)
            rnd = series_lib.load_round(state_root, series_id, round_id)
            if not rnd.get("grid") and str(rnd.get("status") or "") not in ("open", "quali"):
                pass
            rnd["join_url"] = join
            rnd["race_http_port"] = http_port
            series_lib.set_round_status(rnd, "racing")
            series_lib.save_round(state_root, series_id, round_id, rnd)
            refresh_page(series_id, join_url=join)
        except (FileNotFoundError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        role = discord.utils.get(interaction.guild.roles, name=str(spec.get("discordRole") or series_id)) if interaction.guild else None
        ping = role.mention if role else ""
        ch_id = str(rnd.get("discord_channel_id") or "")
        if interaction.guild and ch_id.isdigit():
            ch = interaction.guild.get_channel(int(ch_id))
            if isinstance(ch, discord.TextChannel):
                await ch.send(f"{ping} **Race is live** — {join or f'httpPort {http_port}'}")
        await interaction.followup.send(f"Round `{round_id}` → racing. Join: {join or http_port}", ephemeral=True)

    @practice.command(name="race-join", description="Join link when the race server is live")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def race_join(interaction: discord.Interaction, series_id: str, round_id: str) -> None:
        try:
            rnd = series_lib.load_round(state_root, series_id, round_id)
        except FileNotFoundError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if str(rnd.get("status") or "") != "racing" or not rnd.get("join_url"):
            await interaction.response.send_message("Race server is not live.", ephemeral=True)
            return
        await interaction.response.send_message(f"Join: {rnd['join_url']}", ephemeral=True)

    @admin.command(name="results-import", description="Import finish order (JSON array)")
    @app_commands.describe(
        results_json='JSON list: [{"steam_id":"…","name":"…","pos":1,"best_lap_ms":91234}, …]'
    )
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def results_import(
        interaction: discord.Interaction,
        series_id: str,
        round_id: str,
        results_json: str,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        try:
            finishes = json.loads(results_json)
            if not isinstance(finishes, list):
                raise ValueError("expected JSON array")
            spec = series_lib.load_catalog(catalog, series_id, state_root)
            rnd = series_lib.load_round(state_root, series_id, round_id)
            scored = series_lib.apply_race_points(
                finishes,
                [int(x) for x in (spec.get("points") or [])],
                fastest_lap_point=int(spec.get("fastestLapPoint") or 0),
            )
            rnd["results"] = {"provisional": True, "finishes": scored}
            series_lib.set_round_status(rnd, "provisional")
            series_lib.save_round(state_root, series_id, round_id, rnd)
            refresh_page(series_id)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            await interaction.response.send_message(f"Import failed: {exc}", ephemeral=True)
            return
        lines = [f"P{f.get('pos')} {f.get('name')} — {f.get('points')} pts" for f in scored]
        await interaction.response.send_message("Provisional:\n" + "\n".join(lines), ephemeral=True)

    @admin.command(name="results-finalize", description="Finalize round points and archive channel")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def results_finalize(interaction: discord.Interaction, series_id: str, round_id: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("Run in the server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            rnd = series_lib.load_round(state_root, series_id, round_id)
            results = rnd.get("results")
            if not results:
                raise ValueError("no results — run /admin results-import first")
            results["provisional"] = False
            rnd["results"] = results
            series_lib.set_round_status(rnd, "final")
            series_lib.save_round(state_root, series_id, round_id, rnd)
            refresh_page(series_id)
            meta = series_lib.load_json(state_root / "series" / series_id / "meta.json", {})
            archive_id = meta.get("discord_category_archive")
            parent = interaction.guild.get_channel(int(archive_id)) if str(archive_id or "").isdigit() else None
            ch_id = str(rnd.get("discord_channel_id") or "")
            if ch_id.isdigit():
                ch = interaction.guild.get_channel(int(ch_id))
                if isinstance(ch, discord.TextChannel):
                    if isinstance(parent, discord.CategoryChannel):
                        await ch.edit(category=parent)
                    await ch.set_permissions(interaction.guild.default_role, overwrite=discord.PermissionOverwrite(view_channel=True, send_messages=False))
                    series_lib.set_round_status(rnd, "archived")
                    series_lib.save_round(state_root, series_id, round_id, rnd)
                    refresh_page(series_id)
        except (FileNotFoundError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(f"Round `{round_id}` finalized and archived.", ephemeral=True)

    @admin.command(name="round-archive", description="Archive round channel without finalizing results")
    @app_commands.autocomplete(series_id=series_autocomplete, round_id=round_autocomplete)
    async def round_archive(interaction: discord.Interaction, series_id: str, round_id: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("Run in the server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            rnd = series_lib.load_round(state_root, series_id, round_id)
            meta = series_lib.load_json(state_root / "series" / series_id / "meta.json", {})
            archive_id = meta.get("discord_category_archive")
            parent = interaction.guild.get_channel(int(archive_id)) if str(archive_id or "").isdigit() else None
            ch_id = str(rnd.get("discord_channel_id") or "")
            if ch_id.isdigit():
                ch = interaction.guild.get_channel(int(ch_id))
                if isinstance(ch, discord.TextChannel):
                    if isinstance(parent, discord.CategoryChannel):
                        await ch.edit(category=parent)
                    await ch.set_permissions(
                        interaction.guild.default_role,
                        overwrite=discord.PermissionOverwrite(view_channel=True, send_messages=False),
                    )
            series_lib.set_round_status(rnd, "archived")
            series_lib.save_round(state_root, series_id, round_id, rnd)
            refresh_page(series_id)
        except (FileNotFoundError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(f"Archived `{round_id}`.", ephemeral=True)

    @admin.command(name="push-standings", description="Refresh standings JSON for the player page")
    @app_commands.autocomplete(series_id=series_autocomplete)
    async def series_push_standings(interaction: discord.Interaction, series_id: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            await interaction.response.send_message(f"Need `{admin_role}`.", ephemeral=True)
            return
        try:
            path = series_lib.write_page_payload(state_root, catalog, series_id, pages_url=_pages_url())
        except (FileNotFoundError, ValueError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        acctl = os.environ.get("AC_PUSH_STANDINGS", "").strip()
        msg = f"Wrote `{path}`."
        if acctl:
            try:
                subprocess.run(acctl.split(), check=True, capture_output=True, text=True, timeout=60)
                msg += " Pushed to Pages."
            except (subprocess.CalledProcessError, OSError) as exc:
                msg += f" Push failed: {exc}"
        await interaction.response.send_message(msg, ephemeral=True)

    bot.tree.add_command(admin)
    bot.tree.add_command(practice)
