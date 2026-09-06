#!/usr/bin/env bash
# Cheap syntax + Nix format checks. No network, no game content.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

python -m compileall -q bot scripts shared sidecar

# Host/module Nix is not rfc-formatted yet. Check the flake only so
# CI stays green without a tree-wide reformat.
nixfmt --check flake.nix
