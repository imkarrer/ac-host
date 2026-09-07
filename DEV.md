# Dev / test environment

Isolated stack on the same NixOS box as production. Uses ports **9608 / 8089 / 8189** (slot 8) so live lobbies on 9600–9602 are not restarted.

**Player page (dev):** https://imkarrer.github.io/ac-practice/dev/  
Status push writes `dev/leaderboard.json` in the same `ac-practice` repo (not a second Pages site). Prod keeps `leaderboard.json`.

## One-time on the box

```bash
sudo cp /var/lib/ac-host/src/compose/env.dev.example /var/lib/ac-host-dev/.env
# Edit AC_ADMIN_PASSWORD if needed.
sudo nixos-rebuild switch --flake /var/lib/ac-host/src#ac-box
```

Seed status-push (same `gh` token as prod; different path):

```bash
gh auth token | sudo AC_STATE=/var/lib/ac-host-dev python3 /var/lib/ac-host/src/scripts/seed_github_env.py --env dev
```

`services.ac-host-dev.enable = true` in the host config registers the unit but does **not** add it to `multi-user.target` — start it manually.

## Start / stop dev only

```bash
sudo systemctl start ac-host-dev
sudo systemctl status ac-host-dev
sudo systemctl stop ac-host-dev
```

Or from the repo:

```bash
export AC_STATE=/var/lib/ac-host-dev AC_CONTENT=/var/lib/ac-host/content
python3 scripts/acctl.py --env dev up-static
python3 scripts/acctl.py --env dev down-static --all
```

After changing status-push env only (no lobby restart):

```bash
python3 scripts/acctl.py --env dev restart-plugin
```

## Restart prod plugin after deploy (no lobby kick)

After copying an updated `sidecar/` tree:

```bash
python3 /var/lib/ac-host/src/scripts/acctl.py --env prod restart-plugin
```

## Livery picker experiments

Dev lobby: **`[DEV] Practice — Blackhawk Farmsℹ8189`**

| Id | `RENDER_SKIN_MODE` | What to verify |
| --- | --- | --- |
| A | `pinned` | Always spawns Bianco (baseline) |
| B | `empty` | Click Nero in CM lobby row → `race.ini` SKIN= and in-game spawn |
| C | `empty` | Pick on Content → Cars, Join without row click |
| D | `cycle` | First joiner gets pit 0 skin (variety only) |

```bash
python3 scripts/skin_experiment.py B
```

After each join, check `Documents/Assetto Corsa/cfg/race.ini` and server logs:

```bash
curl -s http://127.0.0.1:8189/api/details | python3 -m json.tool | head -40
docker logs ac-dev-static-dev-blackhawk 2>&1 | tail -20
```

Confirm live status on the **dev** page (not prod): https://imkarrer.github.io/ac-practice/dev/

## Promote to production

Only when the **prod** player page shows the lobby **green** (empty):

```bash
# Example: empty SKIN= after experiment B passes
sudo sed -i 's/^RENDER_SKIN_MODE=.*/RENDER_SKIN_MODE=empty/' /var/lib/ac-host/.env  # if you add it
python3 scripts/acctl.py --env prod up-static --only blackhawk
```

Prod races reserve slots **8–11** for dev (`DEV_RESERVED_SLOTS` in `acctl.py`).
