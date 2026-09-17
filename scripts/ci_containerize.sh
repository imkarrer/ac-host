#!/usr/bin/env bash
# Build the bot/sidecar image from .flox/env/manifest.toml and hand it to the
# box's Docker daemon. Two modes, matching the two sides of the pipeline's
# `wait: ~`:
#
#   build    (every branch, before the wait)  flox containerize the manifest,
#            load it into the daemon as ac-host-env:<sha>, and prove the
#            entrypoints import inside THAT image. Red here blocks queue-prod,
#            like a failing test.
#   promote  (main only, after the wait)      tag ac-host-env:<sha> as
#            ac-host-env:latest, which compose/docker-compose.yml runs, and drop
#            the sha tags nothing references any more.
#
# Why this is a CI step and not a Dockerfile: the manifest is what the tests
# ran under (the plugin activates it), so the closure that ships is the
# closure that was tested, and the box never assembles a runtime at 03:00 --
# `docker compose up --build` used to pull python:3.12-slim and pip-install
# from PyPI in the window. This agent runs ON ac-box with /var/run/docker.sock
# mounted, so `--runtime docker` lands the image exactly where compose looks
# for it; no registry, no MinIO push, no pull.
#
# The code is not in the image; compose bind-mounts the tree at /repo. The
# smoke test below therefore mounts nothing: the checkout lives on a docker
# volume inside the agent, which is not a path the daemon can bind, so it
# copies the tree into a created container with `docker cp` (a tar over the
# socket) and starts it. Not stdin: the image's entrypoint is the flox
# activation, and flox 1.14's activation does not pass stdin through to the
# command (verified: `echo hi | docker run -i <image> python -c
# 'sys.stdin.read()'` reads ''; the same with --entrypoint python reads it).
# Same files, same image, same PYTHONPATH the manifest's [profile] sets from
# AC_REPO.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

IMAGE=ac-host-env
mode="${1:-build}"
sha="${BUILDKITE_COMMIT:-$(git rev-parse HEAD)}"
# flox names the image after .flox/env.json's "name"; we re-tag it under the
# name compose references and drop the original so `docker images` shows one.
flox_name="$(grep -oE '"name": *"[^"]+"' .flox/env.json | sed -E 's/.*"([^"]+)"$/\1/')"

case "$mode" in
  build)
    echo "--- :flox: containerize $flox_name -> $IMAGE:$sha"
    flox containerize --runtime docker --tag "$sha"
    if [ "$flox_name" != "$IMAGE" ]; then
      docker tag "$flox_name:$sha" "$IMAGE:$sha"
      docker rmi "$flox_name:$sha" >/dev/null
    fi
    docker image inspect "$IMAGE:$sha" --format 'size {{.Size}} bytes, {{len .RootFS.Layers}} layers'

    echo "--- :python: entrypoints import inside $IMAGE:$sha"
    # scripts/ci_image_smoke.py, run by the image's own python against the
    # tree copied to /repo. AC_REPO is what the manifest's [profile] builds
    # PYTHONPATH from when there is no FLOX_ENV_PROJECT.
    # --cgroup-parent batch.slice: this runs on the prod box on every branch
    # push, and a Docker tenant fences its own containers (ADR 0005) -- the
    # same slice the agent itself runs in (compose/docker-compose.buildkite.yml).
    cid="$(docker create --cgroup-parent batch.slice -e AC_REPO=/repo "$IMAGE:$sha" python /repo/scripts/ci_image_smoke.py)"
    trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
    git archive --format=tar --prefix=repo/ HEAD bot sidecar shared scripts | docker cp - "$cid:/"
    docker start -a "$cid"
    ;;
  promote)
    echo "--- :docker: $IMAGE:$sha -> $IMAGE:latest"
    docker image inspect "$IMAGE:$sha" >/dev/null 2>&1 \
      || { echo "$IMAGE:$sha is not in the daemon; the build step did not run on this agent?"; exit 1; }
    docker tag "$IMAGE:$sha" "$IMAGE:latest"
    # Keep this sha and whatever `latest` now is (the same image); untag the
    # rest. Layers are shared between builds of the same lock, so this is tag
    # hygiene, not disk pressure -- `docker images` should read as one image.
    keep="$(docker image inspect "$IMAGE:latest" --format '{{.Id}}')"
    docker images "$IMAGE" --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
      | while read -r ref id; do
          case "$ref" in "$IMAGE:latest"|"$IMAGE:$sha") continue ;; esac
          full="$(docker image inspect "$ref" --format '{{.Id}}')"
          [ "$full" = "$keep" ] && continue
          echo "untag $ref"
          docker rmi "$ref" >/dev/null || true
        done
    docker images "$IMAGE"
    ;;
  *)
    echo "usage: $0 [build|promote]" >&2
    exit 2
    ;;
esac
