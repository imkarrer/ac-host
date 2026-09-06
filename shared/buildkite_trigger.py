"""Trigger a Buildkite build via the REST API (urllib — no extra dep)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def configured(
    *,
    token: str | None = None,
    org: str | None = None,
    pipeline: str | None = None,
) -> bool:
    token = token if token is not None else os.environ.get("BUILDKITE_API_TOKEN", "").strip()
    org = org if org is not None else os.environ.get("BUILDKITE_ORG", "").strip()
    pipeline = pipeline if pipeline is not None else os.environ.get("BUILDKITE_PIPELINE", "").strip()
    return bool(token and org and pipeline)


def build_payload(
    *,
    commit: str = "HEAD",
    branch: str = "main",
    message: str = "",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"commit": commit, "branch": branch}
    if message:
        payload["message"] = message
    if env:
        payload["env"] = env
    return payload


def trigger(
    *,
    token: str | None = None,
    org: str | None = None,
    pipeline: str | None = None,
    commit: str = "HEAD",
    branch: str = "main",
    message: str = "",
    env: dict[str, str] | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    token = (token if token is not None else os.environ.get("BUILDKITE_API_TOKEN", "")).strip()
    org = (org if org is not None else os.environ.get("BUILDKITE_ORG", "")).strip()
    pipeline = (pipeline if pipeline is not None else os.environ.get("BUILDKITE_PIPELINE", "ac-host")).strip()
    if not token or not org or not pipeline:
        raise RuntimeError("BUILDKITE_API_TOKEN, BUILDKITE_ORG, and BUILDKITE_PIPELINE are required")
    url = f"https://api.buildkite.com/v2/organizations/{org}/pipelines/{pipeline}/builds"
    body = json.dumps(build_payload(commit=commit, branch=branch, message=message, env=env)).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Buildkite trigger failed HTTP {exc.code}: {detail}") from exc


def trigger_downtime() -> dict[str, Any] | None:
    """Queue the 03:00 apply + recycle job. None if Buildkite env is missing."""
    if not configured():
        return None
    return trigger(message="03:00 apply + recycle", env={"DOWNTIME": "1"})
