"""Trigger a Buildkite build via the REST API (urllib — no extra dep).

Three pipelines in org isaac-karrer, one file each:

- ``BUILDKITE_PIPELINE`` (default ``ac-host``) — GitHub CI
- ``BUILDKITE_PIPELINE_OPS`` (default ``ac-host-ops``) — downtime / emergency
- ``BUILDKITE_PIPELINE_SERIES`` (default ``ac-host-series``) — race pack
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def pipeline_slug(kind: str = "ci") -> str:
    if kind == "ops":
        return os.environ.get("BUILDKITE_PIPELINE_OPS", "ac-host-ops").strip() or "ac-host-ops"
    if kind == "series":
        return os.environ.get("BUILDKITE_PIPELINE_SERIES", "ac-host-series").strip() or "ac-host-series"
    return os.environ.get("BUILDKITE_PIPELINE", "ac-host").strip() or "ac-host"


def configured(
    *,
    token: str | None = None,
    org: str | None = None,
    pipeline: str | None = None,
) -> bool:
    token = token if token is not None else os.environ.get("BUILDKITE_API_TOKEN", "").strip()
    org = org if org is not None else os.environ.get("BUILDKITE_ORG", "").strip()
    if pipeline is None:
        pipeline = pipeline_slug("ci")
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
    pipeline = (pipeline if pipeline is not None else pipeline_slug("ci")).strip()
    if not token or not org or not pipeline:
        raise RuntimeError("BUILDKITE_API_TOKEN, BUILDKITE_ORG, and a pipeline slug are required")
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
    """Queue apply + recycle on the ops pipeline. None if Buildkite env is missing."""
    if not configured():
        return None
    return trigger(
        pipeline=pipeline_slug("ops"),
        message="apply + recycle",
        env={"DOWNTIME": "1"},
    )


def trigger_emergency() -> dict[str, Any] | None:
    """Queue drain + resume on the ops pipeline. None if Buildkite env is missing."""
    if not configured():
        return None
    return trigger(
        pipeline=pipeline_slug("ops"),
        message="emergency apply now",
        env={"EMERGENCY": "1"},
    )


def trigger_series_pack(series_id: str, round_id: str) -> dict[str, Any] | None:
    """Queue the race-pack job. None if Buildkite env is missing."""
    if not configured():
        return None
    return trigger(
        pipeline=pipeline_slug("series"),
        message=f"Race pack {series_id} {round_id}",
        env={"SERIES_ID": series_id, "ROUND_ID": round_id},
    )
