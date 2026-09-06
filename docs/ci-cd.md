# CI/CD (Buildkite + Flox)

The Buildkite **agent runs on ac-box**. Jobs write files under
`/var/lib/ac-host`. They do **not** SSH. Green `main` only **queues** a
tree. The Discord countdown at mark 0 queues **`ac-host-ops`** with
`DOWNTIME=1`, which applies that tree and recycles practice. Last
`queue-prod` wins — no manual gate.

Three Buildkite pipelines, one YAML each. A GitHub push cannot recycle.

| Pipeline | YAML | Who starts it |
| --- | --- | --- |
| **`ac-host`** | `.buildkite/pipeline.yml` | GitHub push/PR |
| **`ac-host-ops`** | `.buildkite/ops.yml` | Bot countdown or New Build (`DOWNTIME=1` / `EMERGENCY=1`). No GitHub webhook |
| **`ac-host-series`** | `.buildkite/series.yml` | `/admin quali-close`. No GitHub webhook |

Race night (start/stop quali and race) stays on the Discord bot +
`acctl`. Buildkite only bakes the numbered-livery zip after quali-close.

## Jobs

| Job | Pipeline | When | Implementation | Kicks? |
| --- | --- | --- | --- | --- |
| **Unit tests** | `ac-host` | every push | `scripts/ci_test.sh` inside Flox | no |
| **Lint** | `ac-host` | every push | `scripts/ci_lint.sh` (`compileall` + `nixfmt --check flake.nix`) | no |
| **Queue prod** | `ac-host` | green `main` | `scripts/ci_queue_prod.py` overwrites `/var/lib/ac-host/pending-src` (fold) | no |
| **Publish pages** | `ac-host` | green `main` | `scripts/ci_publish_pages.py` renders `site/` and copies allowed files into `AC_PAGES_CHECKOUT`. Never touches `leaderboard.json` | no |
| **Downtime** | `ac-host-ops` | bot countdown mark 0, `DOWNTIME=1` | `scripts/ci_downtime.py`: apply pending, then one `recycle-static`. Same calendar day will not recycle twice. `/downtime-drill` does not queue this | yes |
| **Emergency apply** | `ac-host-ops` | New Build with `EMERGENCY=1` | `scripts/ci_apply_now.py` writes `apply-now.json` (drain + resume) | yes |
| **Series race pack** | `ac-host-series` | `/admin quali-close` sets `SERIES_ID` | `scripts/ci_series_pack.sh` → `generate_series_liveries.py` + `publish_series_race_pack.py`. If Buildkite is unset, the bot bakes in-process (old path) | no |

Not jobs (on purpose):

| Step | Owner |
| --- | --- |
| Signup / quali / race start / grid lock | Discord `/admin` + `acctl` on the box |
| `nixos-rebuild` | Manual, empty lobby only |
| Series race container | Still `acctl start-race` until `start-series` exists |

## Why no SSH

The agent compose file mounts `/var/lib/ac-host`. Queue and pages are
file copies. Emergency apply is a flag file. Downtime apply + recycle
runs inside the job the bot queues (docker.sock + the same `acctl` the
timer used).

```text
green main → pending-src (overwrites; last SHA wins)
bot mark 0 → DOWNTIME=1 → apply pending-src → src → recycle-static once
```

Do **not** add a Buildkite cron schedule and do **not** leave
`ac-host-nightly.timer` enabled — those would recycle a second time.
`/downtime-drill` is Discord only. Cancel any builds still sitting on
the old Apply-now block; do not Unblock them.

## First time

1. Sign up at [buildkite.com](https://buildkite.com) with GitHub (`imkarrer`).
   Org slug is **`isaac-karrer`**. Pipelines live at
   [buildkite.com/isaac-karrer](https://buildkite.com/isaac-karrer).
2. **Three pipelines**, same GitHub repo `imkarrer/ac-host`, cluster
   **Default cluster**, queue **`self`**:

   | Slug | First step | GitHub builds |
   | --- | --- | --- |
   | `ac-host` | `buildkite-agent pipeline upload` | on (push + PR) |
   | `ac-host-ops` | `buildkite-agent pipeline upload .buildkite/ops.yml` | **off** |
   | `ac-host-series` | `buildkite-agent pipeline upload .buildkite/series.yml` | **off** |

   Existing `ac-host` stays the CI pipeline. Ops and series must not use
   the default upload path or a push will run the wrong file.
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

4. Optional, so the bot can queue ops/series: set
   `BUILDKITE_API_TOKEN`, `BUILDKITE_ORG=isaac-karrer`,
   `BUILDKITE_PIPELINE=ac-host`, `BUILDKITE_PIPELINE_OPS=ac-host-ops`,
   `BUILDKITE_PIPELINE_SERIES=ac-host-series` in `/var/lib/ac-host/.env`
   and rebuild the bot.
5. Optional pages push: clone `ac-practice` to `$AC_PAGES_CHECKOUT` and
   set `AC_PAGES_PUSH=1`.
6. Rebuild the bot so mark 0 can POST `ac-host-ops` with `DOWNTIME=1`.
   Then `systemctl disable --now ac-host-nightly.timer` so only one recycle.
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
| Bucket / endpoint / region | `.buildkite/*.yml` + image bake args | no |
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
