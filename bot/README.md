# Discord whitelist bot

Players **request** a Steam link; admins **approve/deny**. Nobody self-whitelists.

## Player flow

1. Steam → your profile → right‑click → **Copy Page URL**.
   **Either** URL is accepted:
   - `https://steamcommunity.com/id/name` (what Steam usually copies)
   - `https://steamcommunity.com/profiles/7656…` (numeric)
   A bare 17-digit SteamID64 also works.
2. In Discord: `/steam-request` and paste that URL.
3. Bot checks the URL (and resolves `/id/` via Steam’s public `?xml=1` profile) so “not found” profiles are rejected.
4. A todo lands in the **review channel** with **Approve** / **Deny** buttons and a ping for role `ac-admin`.

## Admin flow

| Action | How |
| --- | --- |
| Approve | Click **Approve** on the review message, or `/steam-approve user:@Alice` |
| Deny | Click **Deny**, or `/steam-deny user:@Alice` |
| Kick access later | `/steam-unlink user:@Alice` |

Admins = Discord role **`ac-admin`** or permission **Manage Server**.

On approve, the bot writes `whitelist.json` (`enabled: true`) and tries to grant role **`ac-practice`**.

## One-time Discord setup

1. https://discord.com/developers/applications → New Application → Bot → copy token.
2. Enable **Server Members Intent**.
3. OAuth2 URL Generator: scopes `bot` + `applications.commands`; permissions Manage Channels, Manage Roles, Send Messages, Manage Messages, Embed Links, Read Message History, Use Slash Commands.
4. Invite the bot. Create roles **`ac-admin`** and **`ac-practice`**. Put the bot’s role **above** `ac-practice` if it should assign that role.
5. Run `scripts/setup_discord.py` inside the bot container to create `#welcome`, `#server-status`, `#now-driving`, `#setups-and-help`, private `#ac-whitelist` / `#staff`, and pinned posts. It prints `DISCORD_REVIEW_CHANNEL_ID` — put that in `/var/lib/ac-host/.env` and restart the bot.

## `.env` on the NixOS box

```bash
DISCORD_TOKEN=...
DISCORD_ADMIN_ROLE=ac-admin
DISCORD_REQUIRED_ROLE=ac-practice
DISCORD_REVIEW_CHANNEL_ID=123456789012345678
# DISCORD_VERIFY_PROFILE=0   # only if Steam blocks the bot’s HTTP check
```

```bash
cd /var/lib/ac-host/src
docker compose -f compose/docker-compose.yml --env-file /var/lib/ac-host/.env --profile bot up -d --build bot
docker logs -f ac-host-bot-1
```

Pending requests are stored in `/var/lib/ac-host/steam_requests.json`. Slash commands can take up to a minute to appear after first sync.

The bot keeps a live player-page mirror in `#server-status` (`DISCORD_STATUS_CHANNEL_ID`): join buttons first, then who’s in each lobby, then the garage. It rereads `leaderboard.json` every 20s. `/practice` reprints that card ephemerally.

## Livery preference (one car + color)

| Command | Who | Effect |
| --- | --- | --- |
| `/livery-set` | Bot-approved player | Save one `{car, skin}`; posted in the channel; unique car+color |
| `/livery-show` / `/livery-clear` | Bot-approved player | Inspect / remove |
| `/livery-admin-set` | Admin | Set by SteamID64 (manual rows / testing) |

`/livery-set` (and show/clear) require a Discord-linked row from `/steam-request` → Approve. Manual `whitelist.json` rows (`discord_id: "0"`) get a “register with the bot” error, not a preference.

A reserved livery holds a pit slot. Approval priority: **local CVSCC members**, then **SSCLAC members**, then everyone else.

On the next practice lobby restart, `render_cfg` puts a **GUID-reserved pit** first in `entry_list.ini` so that Steam ID gets that car/skin. Guests still use open default pits.

**Does not apply mid-session** — restart that lobby when the player page is green.

Practice cars are listed on the public page (catalog `PRACTICE_CARS`). Want another? Post in **#feature-requests** — we add by need.
