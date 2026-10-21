#!/usr/bin/env bash
# Build the three images the experiment compares, inside a Linux container
# (Flox containerizes natively on Linux), writing tarballs to out/.
#   dev      today's production: the dev environment, dev mode
#   samerun  the same dev environment, containerized in run mode
#   runtime  the published package (imkarrer/ac-host-services) in a run-mode
#            runtime environment; needs FLOX_FLOXHUB_TOKEN set (flox auth token)
set -euo pipefail
wt="$(cd "$(dirname "$0")/../.." && pwd)"
repo="$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir)/.."
mkdir -p "$wt/experiments/run-mode/out"
docker run --rm \
  -e FLOX_FLOXHUB_TOKEN -e FLOX_DISABLE_METRICS=true \
  -v flox-run-mode-nix:/nix \
  -v "$(cd "$repo" && pwd)":"$(cd "$repo" && pwd)" \
  -w "$wt" \
  ghcr.io/flox/flox:latest \
  bash -euo pipefail -c '
    git config --global --add safe.directory "*"
    out=experiments/run-mode/out
    flox --version
    [ -f $out/dev.tar ] || flox containerize -d . --mode dev -f $out/dev.tar --tag dev
    [ -f $out/samerun.tar ] || flox containerize -d . --mode run -f $out/samerun.tar --tag samerun
    flox containerize -d experiments/run-mode/runtime -f $out/runtime.tar --tag runtime
  '
