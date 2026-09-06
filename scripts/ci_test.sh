#!/usr/bin/env bash
# Unit tests that do not need game content or a live box.
# Tests that touch KN5s / skins skip themselves when content/ is missing.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

export PYTHONPATH="$root/scripts:$root/bot:$root/sidecar:$root/shared${PYTHONPATH:+:$PYTHONPATH}"

python -m unittest discover -s scripts -p 'test_*.py' -v
python -m unittest discover -s bot -p 'test_*.py' -v
python -m unittest discover -s sidecar -p 'test_*.py' -v
python -m unittest discover -s shared -p 'test_*.py' -v
