# ac-host

NixOS + Docker stack for always-on Assetto Corsa practice lobbies and extra race containers on different ports. This folder is **not** game content. Keep it next to the Steam install so you can pack tracks from here; copy the git tree to the NixOS box.

## What is here

| Path | Role |
| --- | --- |
| `catalog/tracks/*.json` | Add a track by copying a file (folder name, pits, cars) |
| `catalog/statics.json` | Always-on practice lobbies and which ports they own |
| `scripts/sync_content.py` | Copy server-side cars/tracks from this AC install |
| `scripts/pack_content.py` | Zip cars/tracks locally; use `publish_124.py` for the GitHub Release |
| `scripts/publish_124.py` | Pack and upload patched 124 to GitHub Releases |
| `site/` | Public GitHub Pages player README (see `site/README.md`) |
| `scripts/check_car.py` | Reject a car with DX11-illegal textures or missing blurred-object meshes |
| `scripts/render_cfg.py` | Write `server_cfg.ini` + `entry_list.ini` |
| `scripts/acctl.py` | Start/stop static lobbies and race containers |
| `sidecar/` | SteamID whitelist via `AUTH_PLUGIN_ADDRESS` |
| `bot/` | Discord `/steam-link` (manual bot token later) |
| `modules/ac-host.nix` | Docker, firewall port range, systemd static lobbies |
| `hosts/ac-box/` | Example NixOS host — replace hardware-configuration.nix on the box |

Three practice lobbies stay up together (124, GR86, Civic FK8, NA Miata, Elise SC, E30): **Blackhawk Farms**, **Brainerd Competition**, **Brainerd Donnybrooke**. Magione stays in the catalog as a stock-track fallback for races. The GR86 and Civic need Custom Shaders Patch. The player README and live leaderboard are on **GitHub Pages** (`site/`); the home box pushes status outbound — no `:8099`.

## On this Windows machine (content)

From `ac-host/`:

```powershell
python scripts/sync_content.py --track blackhawk
python scripts/sync_content.py --track brainerd-competition
python -m unittest sidecar/test_auth.py
```

Copy `content/` and the git tree to the NixOS box (`/var/lib/ac-host/src` and `/var/lib/ac-host/content`).

## Deploy over SSH

The box on this LAN is `192.168.1.50` (OpenSSH 10.5). A deploy key lives at `%USERPROFILE%\.ssh\id_ed25519_ac-host` and is listed in `hosts/ac-box/ssh-keys.nix`. Password SSH stays on until that file is non-empty **and** you rebuild.

From `ac-host/`, type the installer account password once:

```powershell
python scripts/bootstrap_ssh.py --host 192.168.1.50 --user isaac
```

Use the username you created in the NixOS installer if it is not `isaac`. That copies the pubkey to that user and to root, writes `Host ac-box` in `~/.ssh/config`, and pulls `hardware-configuration.nix`. After it prints `key-login-ok`:

```powershell
ssh ac-box
```

Then copy the tree and switch (do this **after** hardware-config is real, or the first rebuild can miss disks):

```powershell
ssh ac-box "sudo mkdir -p /var/lib/ac-host/src /var/lib/ac-host/content"
tar --exclude content --exclude state --exclude .git -cf - . | ssh ac-box "sudo tar -C /var/lib/ac-host/src -xf -"
ssh ac-box "sudo nixos-rebuild switch --flake /var/lib/ac-host/src#ac-box"
```

Copy `content/` separately when you want the tracks on the box (Brainerd is large).

## On the NixOS box

1. Run `bootstrap_ssh.py` from this PC (installer password, once).
2. Confirm `hosts/ac-box/hardware-configuration.nix` was overwritten from the box.
3. Copy packed content to `/var/lib/ac-host/content`.
4. `cp compose/env.example /var/lib/ac-host/.env` and set `AC_ADMIN_PASSWORD`.
5. `nixos-rebuild switch --flake /var/lib/ac-host/src#ac-box`

Or merge `nixosModules.ac-host` into an existing flake and keep your own hardware config.

Without waiting for systemd:

```bash
export AC_STATE=/var/lib/ac-host AC_CONTENT=/var/lib/ac-host/content
python3 scripts/acctl.py --env prod up-static
```

### Dev / test stack (isolated ports)

Manual-only lobby on slot **8** (`9608` / `8089` / `8189`). Does not restart production lobbies. See [`DEV.md`](DEV.md).

```bash
sudo cp compose/env.dev.example /var/lib/ac-host-dev/.env
python3 scripts/acctl.py --env dev up-static
python3 scripts/acctl.py --env prod restart-plugin   # after sidecar updates; no lobby kick
```

| Env | State dir | Compose project | Auth | Static catalog |
| --- | --- | --- | --- | --- |
| `prod` (default) | `/var/lib/ac-host` | `ac-host` | `:18080` | `catalog/statics.json` |
| `dev` | `/var/lib/ac-host-dev` | `ac-host-dev` | `:18081` | `catalog/statics-dev.json` |

Optional `RENDER_SKIN_MODE` in `.env`: `pinned` (prod default), `empty` (let CM send skin), or `cycle` (variety per pit).

### Race that does not touch the lobbies

```bash
python3 scripts/acctl.py start-race --name sprint1 --track magione
# players join IP:9603 (first port not owned by a static lobby)
python3 scripts/acctl.py stop-race sprint1
```

Join from Content Manager (public IP `167.237.13.200`):

| Lobby | Port | Join |
| --- | --- | --- |
| Practice — Blackhawk Farms | `9600` / HTTP `8081` | [Join](https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8081) |
| Practice — Brainerd Competition | `9601` / HTTP `8082` | [Join](https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8082) |
| Practice — Brainerd Donnybrooke | `9602` / HTTP `8083` | [Join](https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8083) |

## Player page (GitHub Pages)

Official `acServer` does not send cars or tracks to joiners. The public join README and live leaderboard live on GitHub Pages (`site/`). Content Manager Online can auto-download **only the patched 124** via `content.json` on the GitHub Release. GR86, Civic, tracks, and CSP must be installed from source links on the page first.

Player steps: `PLAYERS.md`. One-time Pages setup: `site/README.md`.

Pack and upload the 124 from this PC:

```powershell
python scripts/publish_124.py --owner imkarrer
```

`up-static` writes `state/dist/content.json` (124 Release URL only) for the CM details sidecar. Set `AC_GITHUB_OWNER`, `GITHUB_STATUS_TOKEN`, and `GITHUB_STATUS_REPO` in `/var/lib/ac-host/.env` on the box.

## Ports (one UniFi range)

Forward **9600–9615 TCP+UDP**, **8081–8096 TCP**, and **8181–8196 TCP** (Content Manager details) to the NixOS box. Do not add a new rule per race. Confirm the UniFi WAN address is a real public IP (not CGNAT). **8099 is no longer used.**

## Discord / Grid Finder

Not required to get Magione up. When you are ready: create a bot, enable Server Members Intent, create role `ac-practice`, put the token in `.env`, `docker compose --profile bot up -d bot`, set `AUTH_OPEN=0`. Grid Finder is still a manual event listing + results JSON upload.

## Brainerd (Competition + Donnybrooke)

Both layouts are static lobbies in `catalog/statics.json`. Not on disk yet. Download GutBomb 1.1 (free, OverTake login), drag the zip onto Content Manager, then sync once (same folder for both):

```powershell
python scripts/sync_content.py --track brainerd-competition
```

- Download: https://www.overtake.gg/downloads/brainerd-international-raceway.42674/
- Folder after install: `content/tracks/gb_brainerd`
- Layouts: `competition` (16 pits, port 9601), `donnybrooke` (30 pits, we cap at 24, port 9602)

## Add a track after Blackhawk

1. Install the track in Content Manager on this PC.
2. Copy `catalog/tracks/blackhawk.json` to `catalog/tracks/<id>.json`.
3. Set `folder` to the directory name under `content/tracks`, `layout` if it has variants, `maxClients` ≤ pit boxes, and `cars`.
4. `python scripts/sync_content.py --track <id>`
5. For an always-on lobby, add a row to `catalog/statics.json` with the next free `slot` (0 = 9600, 1 = 9601, …). For a one-off, `acctl.py start-race --track <id>`.
