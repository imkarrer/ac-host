#!/bin/sh
# Create the Nix binary-cache bucket and a dedicated MinIO user.
# Idempotent: safe to re-run when compose comes up.
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
  if mc admin user info local "${S3_CACHE_ACCESS_KEY_ID}" >/dev/null 2>&1; then
    echo "minio user ${S3_CACHE_ACCESS_KEY_ID} already exists"
  else
    mc admin user add local "${S3_CACHE_ACCESS_KEY_ID}" "${S3_CACHE_SECRET_ACCESS_KEY}"
  fi
  mc admin policy attach local readwrite --user "${S3_CACHE_ACCESS_KEY_ID}" \
    || mc admin policy set local readwrite "user=${S3_CACHE_ACCESS_KEY_ID}" \
    || true
fi

echo "minio cache bucket ${bucket} ready"
