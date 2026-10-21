# Run mode vs dev mode: experiment results

Run 21 October 2026, Flox 1.18.2, on an M-series Mac (macOS build) and a
colima Ubuntu 24.04 aarch64 VM (Linux images).

The question: production runs the dev environment in dev mode. Flox's docs
describe run mode as the production mode, used by installing finished
packages. What does following that path cost, and does it keep "the same
environment from dev to prod"?

## What was built

| Image | Environment | Mode | How the code gets in |
|---|---|---|---|
| `dev` | the repo's `.flox` (today's production) | dev | bind-mounted at `/repo` |
| `samerun` | the same `.flox` | run | bind-mounted at `/repo` |
| `runtime` | `runtime/.flox`: one package, `ac-host-services` | run | inside the package |

`ac-host-services` is `.flox/pkgs/ac-host-services.nix`: the bot and sidecar
code plus `python312.withPackages [discordpy numpy scipy pillow]`, with one
wrapper command per service. `flox build ac-host-services` builds it.

The `runtime` environment installs it from `flake.nix` here, not from FloxHub,
because `flox publish` needs the commit pushed and a push to this repo starts a
CI build on the race server. The flake pins `nixos-26.05`, so the Linux
`runtime` image's library versions come from that pin; the macOS `flox build`
result below shows the versions the real publish path would have used.

Reproduce: `./build-images.sh`, then `docker load -i out/<name>.tar`.

## Does each image run the services?

| Test | `dev` | `samerun` | `runtime` |
|---|---|---|---|
| `import discord, numpy, scipy, PIL` | ok | `No module named 'discord'` | no bare `python3` (only the four `ac-host-*` commands) |
| `auth` sidecar answers a non-whitelisted SteamID | `1:not on the list` | `1:not on the list` | `1:not on the list` |
| bot starts and reaches its token check | `DISCORD_TOKEN is not set` | `No module named 'discord'` | `DISCORD_TOKEN is not set` |

`auth` uses only the standard library, so it runs everywhere. The bot is the
real test: run mode works once the app is a package, and fails when it isn't.

Why `samerun` fails: Flox builds two environments from one manifest. On macOS
the dev build's `lib/python3.12/site-packages` has 49 entries; the run build
has 12. Both contain `discord`, but only the dev build links its dependencies
(`aiohttp` is missing from the run build), so even setting `PYTHONPATH` by
hand fails in run mode.

## Size

| Image | Tarball | Unpacked | Store paths |
|---|---|---|---|
| `dev` | 2.15 GB | 4.39 GB | 447 |
| `samerun` | 2.15 GB | 4.37 GB | — |
| `runtime` | 2.20 GB | 4.46 GB | 438 |

Run mode didn't make the image smaller. Most of the weight comes from what
`discordpy` pulls in through discord.py's voice support (ffmpeg, ALSA, BlueZ,
CUPS, FluidSynth) and is in every image. The `runtime` image also carries the
Docker CLI, buildx and compose, which the bot's wrapper adds because the bot
manages deploys.

## Versions: the built package vs the dev environment

`flox build` on macOS, 23 min 24 s (some dependencies weren't in the binary
cache), compared with the dev environment CI tests against:

| | `flox build` package | dev environment |
|---|---|---|
| Python | 3.12.14 | 3.12.11 |
| numpy | 2.5.2 | 2.3.2 |
| scipy | 1.18.1 | 1.16.1 |
| Pillow | 12.3.0 | 11.3.0 |
| aiohttp | 3.14.3 | 3.12.15 |
| ffmpeg | 9.0.1 | 7.1.1 |

The dev environment's packages resolve from a catalog snapshot dated
2025-08-27 (`manifest.lock`); `flox build` compiled the expression against
`github:flox/nixpkgs` at `4975466d`. Nothing ties the two pins together, so
on the documented run-mode path CI tests one set of library versions and
production runs another.

## Findings

1. Run mode works as designed: it runs packages. An environment of an
   interpreter plus library packages isn't a package, so it can't run in run
   mode, even with `PYTHONPATH` set.
2. Making it a package works (`runtime` passes), but it means a second
   definition of the runtime (the `.nix` file's `withPackages` list beside the
   manifest's `[install]`) and a second pin of the package set, and the two
   drift: 14 months apart in this repo.
3. Run mode didn't save space here; the dependency tree did all the work.
4. The literal "same environment from dev to prod" holds only on the dev-mode
   path this repo already uses.
