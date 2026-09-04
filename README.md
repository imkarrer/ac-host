# ac-host

NixOS + Docker stack for always-on Assetto Corsa practice lobbies and race containers. This folder is **not** game content.

Configure everything in **`.env`** (copy from [`compose/env.example`](compose/env.example)). Nothing personal belongs in the git tree.

## Quick start

```bash
cp compose/env.example .env   # or /var/lib/ac-host/.env on the box
# edit: AC_PUBLIC_IP, AC_BOX_HOST, AC_GITHUB_OWNER, passwords, tokens…
```

| Path | Role |
| --- | --- |
| `catalog/` | Tracks, cars, static lobbies |
| `compose/env.example` | All runtime config knobs |
| `scripts/acctl.py` | Start/stop lobbies (`--env prod\|dev`) |
| `scripts/settings.py` | Reads `.env` for scripts |
| `scripts/render_site.py` | Renders `site/` → `dist/site` from `.env` |
| `modules/ac-host.nix` | NixOS module |
| `site/` | GitHub Pages **templates** (placeholders; push rendered `dist/site`) |

## NixOS box

1. Copy this tree to the host (e.g. `/var/lib/ac-host/src`).
2. `cp compose/env.example /var/lib/ac-host/.env` and set values.
3. Put deploy pubkeys in `hosts/ac-box/ssh-keys.local.nix` (gitignored; see `ssh-keys.nix.example`).
4. Copy `hosts/ac-box/hardware-configuration.nix.example` → `hardware-configuration.nix` (or generate on the box).
5. `nixos-rebuild switch --flake .#ac-box`

```bash
export AC_STATE=/var/lib/ac-host AC_CONTENT=/var/lib/ac-host/content
python3 scripts/acctl.py --env prod up-static
```

Dev stack (slot 8 / HTTP 8089): see [`DEV.md`](DEV.md).

## Player page

Outbound status push + static README live on GitHub Pages (`AC_PAGES_URL`). Render join links from `.env`:

```bash
python scripts/render_site.py          # → dist/site/
# push dist/site contents to your Pages repo (AC_GITHUB_REPO)
```

Pack/upload the patched 124 (optional):

```bash
python scripts/publish_124.py --owner "$AC_GITHUB_OWNER"
```

## Ports

Prefer slot-scoped UniFi forwards (`UNIFI_PF=1`) — see [`docs/plan-unifi-portforwards.md`](docs/plan-unifi-portforwards.md). Do not leave broad ranges open. **8099 is unused.**

## Discord whitelist bot

See [`bot/README.md`](bot/README.md). Set `DISCORD_TOKEN` in `/var/lib/ac-host/.env`, create role `ac-practice`, then `docker compose --profile bot up -d --build bot`.

## License

MIT for this repo’s scripts and Nix. Assetto Corsa, cars, and tracks remain their owners’ property; this repo does not redistribute game assets.
