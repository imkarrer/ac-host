# CI/CD (Buildkite + Flox)

The Buildkite **agent runs on ac-box**. Jobs write files under
`/var/lib/ac-host`. They do **not** SSH. Green `main` only **queues** a
tree. One scheduled build (`DOWNTIME=1` at 03:00 America/Chicago) applies
that tree and recycles practice. Last `queue-prod` wins — do not unblock
old Apply-now steps.

Race night (start/stop quali and race) stays on the Discord bot +
`acctl`. Buildkite only bakes the numbered-livery zip after
`/admin quali-close`.

## Jobs

| Job | When | Implementation | Kicks? |
| --- | --- | --- | --- |
| **Unit tests** | every push (not pack builds) | `.buildkite/pipeline.yml` → `scripts/ci_test.sh` inside Flox | no |
| **Lint** | every push (not pack builds) | `scripts/ci_lint.sh` (`compileall` + `nixfmt --check flake.nix`) | no |
| **Queue prod** | green `main` | `scripts/ci_queue_prod.py` overwrites `/var/lib/ac-host/pending-src` (fold) | no |
| **Downtime** | 03:00 CT schedule, `DOWNTIME=1` | `scripts/ci_downtime.py`: apply pending, then one `recycle-static`. Same calendar day will not recycle twice | yes |
| **Publish pages** | green `main` | `scripts/ci_publish_pages.py` renders `site/` and copies allowed files into `AC_PAGES_CHECKOUT`. Never touches `leaderboard.json` | no |
| **Emergency apply** | New Build with `EMERGENCY=1` | `scripts/ci_apply_now.py` writes `apply-now.json` (drain + resume) | yes |
| **Series race pack** | `/admin quali-close` sets `SERIES_ID` | `scripts/ci_series_pack.sh` → `generate_series_liveries.py` + `publish_series_race_pack.py`. If Buildkite is unset, the bot bakes in-process (old path) | no |

Not jobs (on purpose):

| Step | Owner |
| --- | --- |
| Signup / quali / race start / grid lock | Discord `/admin` + `acctl` on the box |
| `nixos-rebuild` | Manual, empty lobby only |
| Series race container | Still `acctl start-race` until `start-series` exists |

## Why no SSH

The agent compose file mounts `/var/lib/ac-host`. Queue and pages are
file copies. Emergency apply is a flag file. Downtime apply + recycle
runs inside the scheduled job (docker.sock + the same `acctl` the timer
used).

```text
green main → pending-src (overwrites; last SHA wins)
03:00 DOWNTIME=1 → apply pending-src → src → recycle-static once
```

Create the schedule on the pipeline: **Pipeline Settings → Schedules → New**.

- Cron: `0 3 * * * America/Chicago`
- Branch: `main`
- Env: `DOWNTIME=1`
- Queue: `self`

Buildkite may start that job a few minutes after 03:00. Disable
`ac-host-nightly.timer` on the box so systemd does not recycle a second
time the same morning. Cancel any builds still sitting on the old
Apply-now block — do not Unblock all of them.

## First time

1. Sign up at [buildkite.com](https://buildkite.com) with GitHub (`imkarrer`).
   Org slug is **`isaac-karrer`**. Pipelines live at
   [buildkite.com/isaac-karrer](https://buildkite.com/isaac-karrer).
2. **New pipeline** → GitHub repo `imkarrer/ac-host` → cluster **Default
   cluster** → queue **`self`** → keep `buildkite-agent pipeline upload`.
3. On **ac-box**, start the Flox agent image **and** the loopback MinIO cache:

   ```bash
   cp compose/env.buildkite.example compose/.env.buildkite
   # paste BUILDKITE_AGENT_TOKEN=
   # paste MINIO_ROOT_PASSWORD, S3_CACHE_SECRET_ACCESS_KEY, S3_CACHE_SIGNING_KEY
   docker compose -f compose/docker-compose.buildkite.yml --env-file compose/.env.buildkite up -d --build
   ```

   First `compose build` is long: it installs Flox and seeds the Nix store
   with this repo's packages. Keep that off race night. MinIO listens on
   `127.0.0.1:9000` (S3) and `127.0.0.1:9001` (console) only — do not
   publish those ports on the game NIC or WAN.

4. Optional, so `/admin quali-close` queues the pack: set
   `BUILDKITE_API_TOKEN`, `BUILDKITE_ORG=isaac-karrer`, `BUILDKITE_PIPELINE=ac-host`
   in `/var/lib/ac-host/.env` and rebuild the bot.
5. Optional pages push: clone `ac-practice` to `$AC_PAGES_CHECKOUT` and
   set `AC_PAGES_PUSH=1`.
6. Add the 03:00 `DOWNTIME=1` schedule (above). Then
   `systemctl disable --now ac-host-nightly.timer` so only one recycle.
7. Push `.flox/`, `.buildkite/`, and the `ci_*` scripts to `main`.

## Local check

```bash
flox activate
bash scripts/ci_test.sh
bash scripts/ci_lint.sh
```

## New repo

`flox init` → commit `.flox/` → copy `.buildkite/pipeline.yml` → new
Buildkite pipeline on the same agent.

## Nix binary cache (MinIO)

The plugin image and every pipeline step point at bucket `flox-binary-cache`
on `http://minio:9000` (same compose network). After a step, `s3-cache-push:
true` signs the activated closure and writes it back so the next job can
substitute instead of fetching upstream.

| Piece | Where | Secret? |
| --- | --- | --- |
| Bucket / endpoint / region | `.buildkite/pipeline.yml` + image bake args | no |
| Public key | `.buildkite/flox-binary-cache.pub` (also inlined in the pipeline) | no |
| MinIO root + cache user | `compose/.env.buildkite` | yes |
| Nix signing key | `S3_CACHE_SIGNING_KEY` in that env file | **yes** — anyone with it can plant trusted store paths |

Generate or rotate the signing keypair (updates the committed public file):

```bash
bash scripts/ci_nix_cache_key.sh
# copy the secret line into compose/.env.buildkite
# update the public key string in .buildkite/pipeline.yml to match
```

A workstation copy of `compose/.env.buildkite` may already have generated
values; copy that file to the box rather than committing it.

## Pinning the plugin

`imkarrer/flox#main` until the plugin has a release tag, then pin
`#v1.0.0`.
