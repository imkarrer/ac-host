#!/usr/bin/env bash
# Bake numbered skins + publish the CM zip. Runs on ac-box (content + KN5s).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

series="${SERIES_ID:?set SERIES_ID}"
state="${AC_STATE:-/var/lib/ac-host}"
build_content="${AC_BUILD:-/var/lib/ac-host/build}/content"
serve="${AC_SERVE_CONTENT:-/var/lib/ac-host/content}"
catalog="${AC_CATALOG:-$root/catalog}"

python scripts/generate_series_liveries.py \
  --series "$series" \
  --state "$state" \
  --catalog "$catalog" \
  --content "$build_content" \
  --serve-content "$serve"

python scripts/publish_series_race_pack.py \
  --series "$series" \
  --state "$state" \
  --catalog "$catalog" \
  --content "$build_content" \
  --content-json "$state/dist/content.json"
