#!/bin/sh
# Create the Nix binary-cache bucket and a dedicated MinIO user.
# Idempotent: safe to re-run when compose comes up, and it does run on every
# `up` (agent depends_on its completion), so what it does with the env it is
# handed is what a rotation costs.
set -eu

endpoint="${MINIO_ENDPOINT:-http://minio:9000}"
bucket="${S3_CACHE_BUCKET:-flox-binary-cache}"

echo "waiting for minio at ${endpoint}..."
i=0
until mc alias set local "${endpoint}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"; do
  i=$((i + 1))
  if [ "${i}" -gt 30 ]; then
    echo "minio did not become ready"
    exit 1
  fi
  sleep 2
done

mc mb --ignore-existing "local/${bucket}"

if [ -n "${S3_CACHE_ACCESS_KEY_ID:-}" ] && [ -n "${S3_CACHE_SECRET_ACCESS_KEY:-}" ]; then
  # No existence guard, on purpose. The server's CreateUser (MinIO
  # RELEASE.2025-09-07 lineage, the image on the box) rewrites an existing
  # user's secret rather than refusing, so `user add` on every start is what
  # makes the stored secret follow the env file. With the guard that was
  # here (`mc admin user info` first, add only when absent) a rotated
  # S3_CACHE_SECRET_ACCESS_KEY started the agent with the new value while
  # MinIO kept the old one, and every cache read and push 403'd until
  # someone re-ran `user add` by hand. Now a rotation is: new value in
  # homelab's sops, switch, bounce ac-host-ci.
  mc admin user add local "${S3_CACHE_ACCESS_KEY_ID}" "${S3_CACHE_SECRET_ACCESS_KEY}"
  mc admin policy attach local readwrite --user "${S3_CACHE_ACCESS_KEY_ID}" \
    || mc admin policy set local readwrite "user=${S3_CACHE_ACCESS_KEY_ID}" \
    || true
fi

echo "minio cache bucket ${bucket} ready"
