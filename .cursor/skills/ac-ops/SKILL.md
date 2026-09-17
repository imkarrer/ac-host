---
name: ac-ops
description: >-
  Operate the Assetto Corsa practice box: reboot/resume, drain for
  maintenance, player-page health light, ntfy heartbeat, and GitHub Pages
  publishes. Use when the box is down, ac-host-static is hung, lobbies did
  not come back, the red/green light is wrong, or the user mentions drain,
  resume, maintenance, heartbeat, or reboot.
---

# Operate ac-box (practice)

SSH `ac-box` (`192.168.1.50`, user from `Host ac-box`). Game NIC is `enp8s0`. Do not assume `eno1` is up.

## After a reboot (do this first)

```text
systemctl is-active ac-host-static docker
docker ps --format '{{.Names}} {{.Status}}'
```

Expected **prod**: `ac-static-blackhawk`, `ac-static-road-america`, `ac-static-gingerman`, `ac-host-auth-1`, `ac-host-plugin-1`, `ac-host-details-1`, `ac-host-bot-1`. HTTP `8081`–`8083` and `8181` return 200.

| Symptom | Cause | Fix |
| --- | --- | --- |
| Lobbies up, no `ac-host-auth-1`/`plugin`/`details`; journal says `sidecars skipped: ac-host-env:latest is not in the Docker daemon` | no green `main` build has run since the image moved to CI (up-static starts lobbies first and skips the sidecars, exit 0) | `docker images ac-host-env`; push to `main` or re-run the last ac-host build so its `image` + `promote-image` steps load it, then `acctl.py resume` |
| Lobbies missing, sidecars up | oneshot died after auth, before `docker run` | `resume` (no rebuild) |
| Page red, box healthy | stale GitHub `updated` or leftover `maintenance.json` | Wait 90s, or `maintenance --off`. Hard-refresh `app.js` |

## Drain / resume (planned downtime)

On the box, from `/var/lib/ac-host/src`:

```text
python3 scripts/acctl.py drain --message "NIC work, back soon."
# … reboot or work …
python3 scripts/acctl.py resume
```

`systemctl stop ac-host-static` now paints **maintenance** then stops lobbies (plugin stays). `systemctl start` / boot runs `up-static` **without** `--build`, waits for lobby HTTP, then clears the banner.

Recreate sidecars only when you changed `sidecar/`, `bot/` or `shared/` (the
code is bind-mounted from the tree; the image `ac-host-env:latest` is built by
CI with `flox containerize` and never on the box):

```text
python3 scripts/acctl.py up-static --recreate
docker compose -f compose/docker-compose.yml --env-file /var/lib/ac-host/.env --profile bot up -d --force-recreate bot
```

## Health light

- **Live ping** = ntfy `heartbeat` every 60s (not a GitHub commit).
- **Failover** = no live ping for 4 min. First paint waits 90s on **Checking…**.
- **`status: maintenance`** in `leaderboard.json` wins over the ping.
- Do **not** heartbeat by rewriting Pages `leaderboard.json`.

## Player page publish

`render_site.py` → copy **only** `index.html`, `app.js`, `style.css`, `dev/index.html` (and `content.json` if cars changed) into `imkarrer/ac-practice`. **Never overwrite live lap rows** in `leaderboard.json`. Bump `?v=` on js/css. Commit with `git -c user.name=… -c user.email=…` (never `git config`).

## Anti-patterns

- `compose up --build` anywhere: there is no Dockerfile for the bot or sidecars; the image is CI's
- `docker cp` + `restart` for the bot
- Killing plugin so the light “goes red” (use `drain` / `maintenance --on`)
- Treating GitHub `updated` as proof the box is dead
