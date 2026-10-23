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

## Second run: no Nix (uv, a manifest build and `flox publish`)

The first run needed a Nix expression and a flake. This run uses only Flox
and standard Python: `pyproject.toml` and `uv.lock` pin the libraries, a
`[build.ac-host-services]` in the manifest installs them into a venv in
`$out` with one wrapper per service, `flox publish` puts the package in the
`imkarrer` catalog, and `runtime/.flox` installs `imkarrer/ac-host-services`
in run mode.

| | Nix expression (first run) | uv manifest build |
|---|---|---|
| `flox build` on macOS | 23 min 24 s | 32 s |
| Package closure (macOS) | 2.5 GiB | 652 MiB |
| Linux `runtime` image, tarball / unpacked | 2.20 GB / 4.46 GB | 882 MB / 1.77 GB |
| Bot starts, `auth` answers | yes / yes | yes / yes |
| Python | 3.12.14 (expression nixpkgs) | 3.12.11 (the environment's own) |
| numpy, scipy, Pillow, aiohttp | 2.5.2, 1.18.1, 12.3.0, 3.14.3 | 2.5.4, 1.18.1, 13.0.0, 3.14.5 (exactly `uv.lock`) |

The image is 59% smaller than today's production image (2.15 GB). That's
PyPI's `discord.py`, which doesn't pull in ffmpeg and the audio stack, not
run mode.

Library versions now come from one pin, `uv.lock`, and the interpreter from
the environment's own lock. CI still tests the catalog libraries (numpy
2.3.2), so the drift is gone only if dev and CI also install from `uv.lock`.

### What went wrong on the way

- **PyPI's Linux wheels need system libraries Nix's Python doesn't have.**
  numpy failed with `libstdc++.so.6` and then `libz.so.1` missing. The
  wrapper adds `libstdc++`; `zlib` still has to be added (install `zlib`, add
  it to `runtime-packages` and the wrapper's library path). The published
  0.0.1 is missing it: the bot starts, because numpy loads only when a livery
  command runs, so a startup check passes and the first livery command would
  crash.
- **Flox's build wrapper hides a venv from a bare `python`.** Each command a
  manifest build produces is wrapped by Flox, which sets `PYTHONPATH` to the
  build environment and starts commands with the base interpreter. The
  services work because each wrapper script's shebang names the venv's
  Python; running the venv's `python` through Flox's wrapper doesn't see the
  venv's packages.
- **The container entrypoint doesn't escape arguments.** `docker run <image>
  echo '(paren)'` fails with a bash syntax error: arguments are joined into
  one `bash -c` string, quoted when they contain spaces, but other shell
  characters aren't escaped.
- **Publishing for Linux needed a Linux machine.** `flox publish` on macOS
  publishes only the macOS build. The Linux publish ran in a container, needed
  the SSH remote rewritten to HTTPS, took about 30 minutes, and ended with
  `Timed out waiting for publish completion` although the package had been
  published.
- **Publishing needs the commit pushed,** which here started a branch build
  on the race server (build 65, passed).

### Fixed in 0.0.2

`zlib` now ships in `runtime-packages` and sits on the wrappers'
`LD_LIBRARY_PATH` beside `libstdc++`. A new command, `ac-host-check`, imports
every service module (including the numpy, scipy and Pillow ones) through the
same wrapper. In the Linux run-mode image built from the published 0.0.2:

    $ docker run --rm ac-host-runtime:runtime ac-host-check
    ac-host-check ok: numpy 2.5.4 scipy 1.18.1 Pillow 13.0.0 discord.py 2.7.1

The image is still 882 MB.

## Fourth route, the one Flox intends: catalog libraries in `runtime-packages`

A closer read of Flox's source and docs found the route the first three runs
missed. A manifest build can list the catalog libraries the
environment already locks in `runtime-packages`; Flox wraps every program the
build produces with a wrapper that sets `PYTHONPATH` to that runtime
environment (flox PR #3337, "we want Flox build packages to be
self-contained").

`[build.ac-host-catlibs]` in `.flox/env/manifest.toml` does it for ac-host:
`runtime-packages = ["python312Full", "discordpy", "numpy", "scipy",
"pillow", "dejavu_fonts", "git", "rsync"]`, and the build only copies the
code and writes the launchers. No uv, no Nix, no library-path workaround.

| | macOS | Linux (container) |
|---|---|---|
| `flox build ac-host-catlibs` | 7 s | ok |
| `ac-host-check` | numpy 2.3.2, scipy 1.16.1, Pillow 11.3.0, discord.py 2.5.2, aiohttp 3.12.15 | same |
| Dev environment (what CI tests) | numpy 2.3.2, scipy 1.16.1, Pillow 11.3.0, discord.py 2.5.2, aiohttp 3.12.15 | — |
| Bot starts | yes | yes |

Same manifest, same lock, same library versions as CI, and it runs in run
mode. The image won't be smaller than today's: the catalog `discordpy`
still pulls in ffmpeg and the audio stack.

Corrections to the earlier sections:
- The version drift applies to Nix expression builds (deliberately since
  flox#4708, v1.18.0) and to uv. Manifest builds use the environment's lock.
- A locally built package can be installed with `[install]
  x.store-path = "/nix/store/..."`; what's missing is a portable way
  (flox#3658).
- The PyPI-wheel fix can be one build-time `auto-patchelf` line instead of
  the re-exec wrapper; the catalog-library route avoids the problem.

## Prototypes for the proposals (22 October 2026)

**One list (proposal 3), with an existing feature.** Marking the dev-only tools
with `pkg-group = "dev-only"` (gh, nixfmt-rfc-style, uv) and dropping
`runtime-packages` from `[build.ac-host-catlibs]`: every package is listed
once, the shipped package contains none of the three tools (git and rsync,
which the bot needs, still ship), the dev shell still has them, and
`ac-host-check` passes with CI's versions. `runtime-packages` trims only the
toplevel group, so a separate group is left out. That's an undocumented side
effect of a feature meant for version conflicts, and each group is a separate
download; the proposal is a documented dev-only flag.

**Ship the environment (proposal 4).** `[build.ac-host-python]` wraps the
environment's own `python3`, so Flox's build wrapper puts the catalog
libraries on its path. `python-runtime/.flox` installs it by store path, in
run mode. Containerized on Linux in run mode, with the repo bind-mounted at
`/repo` and `APP_PYTHONPATH` naming its module folders:

    $ docker run --rm -v "$PWD":/repo:ro -e APP_PYTHONPATH=... \
        ac-host-python-runtime:proposal4 python3 /repo/experiments/run-mode/check_imports.py
    check ok: numpy 2.3.2 scipy 1.16.1 Pillow 11.3.0 discord.py 2.5.2

The bot starts the same way. No app packaging; image 2.16 GB, the same as
today's dev image. Finding: Flox's build wrapper *replaces* `PYTHONPATH`
with the runtime libraries, dropping whatever the user set, so the shim adds
`APP_PYTHONPATH` back in front. A product version would prepend instead.

**The PyPI-wheel fix (issue item 7), confirmed.** `[build.ac-host-services-patchelf]`
runs `auto-patchelf --paths "$out/venv/lib" --libs "$FLOX_ENV/lib"` after
`uv sync` (needs both `auto-patchelf` and `patchelf` installed, plus
`gcc-unwrapped` and `zlib` in `runtime-packages`). On Linux the build reports
"0 dependencies could not be satisfied", and a bare venv Python with
`LD_LIBRARY_PATH` and `LD_AUDIT` unset imports numpy 2.5.4, scipy 1.18.1,
Pillow 13.0.0 and discord.py 2.7.1. That replaces the re-exec wrapper.

Also: once the manifest changed, resolving packages in the container
required a FloxHub login.

## The docs, verbatim: the Python guide's two build recipes (23 October 2026)

The question a customer would ask first: what happens if I follow
https://flox.dev/docs/languages/python#build-with-flox exactly? Tested on a
one-module app, `hello`, whose only dependency is numpy, so ac-host's layout
can't be the cause. Flox 1.18.2.

**Pip** (`docs-pip/`). The guide's whole build is `pip install --target=$out .`.

1. The build fails: `ERROR: Could not find an activated virtualenv (required).`
   Flox's activation writes a `pip.ini` with `require-virtualenv = true`
   whenever pip is installed, and the comment in
   `assets/environment-interpreter/common/etc/profile.d/profile.d.functions`
   says it applies to builds too. The documented recipe can't pass.
2. With `PIP_REQUIRE_VIRTUALENV=false`, it builds, and the program it produces
   fails: `ModuleNotFoundError: No module named 'hello'`. pip puts the app and
   numpy at the top of `$out`, and Flox's build wrapper doesn't put `$out` on
   Python's path.

**Poetry** (`docs-poetry/`). The guide's manifest, unchanged except the
placeholder script name.

- macOS: runs. But `python3.version = ">=3.12"` resolved to Python 3.14, and
  numpy is 2.5.4 from PyPI, not the catalog's.
- Linux (`docs-poetry/linux-check.sh` in `ghcr.io/flox/flox`): numpy fails to
  import everywhere, with `libz.so.1` or `libstdc++.so.6` missing: in the
  activated dev shell, run bare as a run-mode image would, and installed into a
  run-mode environment. The fix is the undocumented `auto-patchelf` step from
  the uv route above.

So neither documented recipe gets a Python app with a compiled dependency
running on Linux, and the one that runs on macOS ships PyPI versions, not the
locked ones dev and CI use. The route that works, catalog libraries with the
build wrapper's PYTHONPATH (fourth route, above), isn't in the guide.

**What an agent is told.** Flox's public agent skills (flox/flox-skills,
`flox-plugin/skills/flox/references/builds.md` line 110) say: "Python package
strategy: Don't bundle Python deps - include `requirements.txt` and setup
script", a script that runs `uv pip install` from PyPI when the app first
starts. The `floxify` skill sets Python up as a venv that the on-activate hook
fills with pip, which exists only in an activated dev shell. Neither mentions
run mode, `runtime-packages` or catalog Python libraries. An agent following
them lands where this repo did: production in dev mode.
