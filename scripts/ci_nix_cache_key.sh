#!/usr/bin/env bash
# Generate or rotate the Nix signing keypair for the MinIO binary cache.
# Writes the secret (0600) and prints the public key to stdout.
#
#   bash scripts/ci_nix_cache_key.sh [secret-path]
#
# Put the secret file's single line into compose/.env.buildkite as
# S3_CACHE_SIGNING_KEY=...  Commit only the public half
# (.buildkite/flox-binary-cache.pub) and update S3_CACHE_PUBLIC_KEY to match.
set -euo pipefail

out="${1:-secrets/flox-binary-cache.secret}"
mkdir -p "$(dirname "${out}")"
umask 177
nix --extra-experimental-features nix-command key generate-secret \
  --key-name flox-binary-cache-1 >"${out}"
chmod 600 "${out}"
pub="$(nix --extra-experimental-features nix-command key convert-secret-to-public <"${out}")"
printf '%s\n' "${pub}" >.buildkite/flox-binary-cache.pub
echo "wrote secret ${out} (gitignored) and .buildkite/flox-binary-cache.pub"
echo "${pub}"
