#!/usr/bin/env python3
"""Push leaderboard.json to GitHub via Contents API (outbound HTTPS only)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

DEBOUNCE_SEC_DEFAULT = 25.0
HTTP_HEADERS = {
    "User-Agent": "ac-host-push-status",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class StatusPusher:
    def __init__(self) -> None:
        self.token = os.environ.get("GITHUB_STATUS_TOKEN", "").strip()
        self.repo = os.environ.get("GITHUB_STATUS_REPO", "").strip()
        self.branch = os.environ.get("GITHUB_STATUS_BRANCH", "main").strip()
        self.path = os.environ.get("GITHUB_STATUS_PATH", "leaderboard.json").strip().lstrip("/")
        self._last_hash: str | None = None
        self._pending: str | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._enabled = bool(self.token and self.repo)
        self._debounce_sec = float(os.environ.get("GITHUB_STATUS_DEBOUNCE_SEC", str(DEBOUNCE_SEC_DEFAULT)))
        if self._enabled:
            print(f"status push enabled -> {self.repo}:{self.branch}/{self.path}")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def schedule(self, text: str) -> None:
        if not self._enabled:
            return
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest == self._last_hash:
            return
        with self._lock:
            self._pending = text
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_sec, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def flush_now(self, text: str | None = None) -> None:
        """Push immediately (used in tests)."""
        if not self._enabled:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            payload = text if text is not None else self._pending
            self._pending = None
        if payload:
            self._put(payload)

    def _flush(self) -> None:
        with self._lock:
            text = self._pending
            self._pending = None
            self._timer = None
        if not text:
            return
        try:
            self._put(text)
        except Exception as exc:
            print(f"status push failed: {exc}")

    def _api_url(self) -> str:
        owner, _, repo = self.repo.partition("/")
        if not owner or not repo:
            raise ValueError(f"invalid GITHUB_STATUS_REPO: {self.repo!r}")
        path = quote(self.path, safe="/")
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    def _get_sha(self) -> str | None:
        url = f"{self._api_url()}?ref={quote(self.branch)}"
        req = Request(url, headers={**HTTP_HEADERS, "Authorization": f"Bearer {self.token}"})
        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("sha")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _put(self, text: str) -> None:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest == self._last_hash:
            return
        sha = self._get_sha()
        try:
            updated = json.loads(text).get("updated") or ""
        except json.JSONDecodeError:
            updated = ""
        payload: dict = {
            "message": f"status {updated}".strip(),
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha
        req = Request(
            self._api_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                **HTTP_HEADERS,
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        with urlopen(req, timeout=30) as resp:
            resp.read()
        self._last_hash = digest
        print(f"status pushed {self.path}")
        self._notify_event(str(updated))


    def _notify_event(self, updated: str) -> None:
        """Outbound ping so the GitHub Pages tab can refresh without a home-box port."""
        post_status_event(updated or "updated")


def post_status_event(message: str) -> None:
    """POST to ntfy. Works without a GitHub token so heartbeats still fire."""
    url = event_url()
    if not url:
        return
    req = Request(
        url,
        data=(message or "updated").encode("utf-8"),
        headers={
            "User-Agent": HTTP_HEADERS["User-Agent"],
            "Content-Type": "text/plain",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            resp.read()
        print(f"status event posted {url}")
    except Exception as exc:
        print(f"status event failed: {exc}")


def notify_heartbeat() -> None:
    post_status_event("heartbeat")


def event_url() -> str:
    explicit = os.environ.get("STATUS_EVENT_URL", "").strip()
    if explicit:
        return explicit
    repo = os.environ.get("GITHUB_STATUS_REPO", "").strip()
    owner, _, name = repo.partition("/")
    if not owner or not name:
        return ""
    return f"https://ntfy.sh/ac-{owner}-{name}-status"


def event_sse_url() -> str:
    explicit = os.environ.get("STATUS_EVENT_SSE", "").strip()
    if explicit:
        return explicit
    base = event_url().rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/sse") else f"{base}/sse"


_pusher: StatusPusher | None = None


def get_pusher() -> StatusPusher:
    global _pusher
    if _pusher is None:
        _pusher = StatusPusher()
    return _pusher


def schedule_push(text: str) -> None:
    get_pusher().schedule(text)


def reset_pusher() -> None:
    global _pusher
    _pusher = None
