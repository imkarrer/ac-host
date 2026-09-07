"""Upload release assets with a token instead of the `gh` CLI.

`publish_cars.py` shells out to `gh`, which is fine on a workstation. ac-box has
no `gh` and no interactive login, so the server-side publish path talks to the
REST API directly with a token from disk. Only urllib, so this works inside the
slim bot image too.
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TOKEN_ENV = "AC_GITHUB_TOKEN"
TOKEN_FILE_ENV = "AC_GITHUB_TOKEN_FILE"
DEFAULT_TOKEN_FILE = "/var/lib/ac-host/secrets/github-token"


def load_token(explicit: str = "") -> str:
    """Token from an argument, the environment, or the secrets file on ac-box."""
    if explicit.strip():
        return explicit.strip()
    env = os.environ.get(TOKEN_ENV, "").strip()
    if env:
        return env
    for candidate in (os.environ.get(TOKEN_FILE_ENV, "").strip(), DEFAULT_TOKEN_FILE):
        if candidate and Path(candidate).is_file():
            token = Path(candidate).read_text(encoding="utf-8").strip()
            if token:
                return token
    raise SystemExit(
        f"no GitHub token; set {TOKEN_ENV}, or {TOKEN_FILE_ENV}, "
        f"or put one line in {DEFAULT_TOKEN_FILE}"
    )


def _request(url: str, token: str, *, method: str = "GET", data: bytes | None = None,
             content_type: str | None = None) -> dict | list | None:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"github {method} {url} -> {exc.code}: {detail}") from exc
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def get_release(owner: str, repo: str, tag: str, token: str) -> dict:
    release = _request(f"{API}/repos/{owner}/{repo}/releases/tags/{tag}", token)
    if not isinstance(release, dict):
        raise SystemExit(f"release {tag} not found in {owner}/{repo}")
    return release


def ensure_release(owner: str, repo: str, tag: str, token: str, *, title: str = "",
                   notes: str = "") -> dict:
    try:
        return get_release(owner, repo, tag, token)
    except SystemExit:
        payload = json.dumps(
            {"tag_name": tag, "name": title or tag, "body": notes}
        ).encode("utf-8")
        created = _request(
            f"{API}/repos/{owner}/{repo}/releases",
            token,
            method="POST",
            data=payload,
            content_type="application/json",
        )
        if not isinstance(created, dict):
            raise SystemExit(f"could not create release {tag}")
        return created


def upload_asset(
    owner: str,
    repo: str,
    tag: str,
    path: Path,
    token: str,
    *,
    clobber: bool = True,
) -> str:
    """Upload one file, replacing any asset of the same name. Returns its URL."""
    path = Path(path)
    release = ensure_release(owner, repo, tag, token)
    name = path.name

    for asset in release.get("assets") or []:
        if asset.get("name") != name:
            continue
        if not clobber:
            raise SystemExit(f"asset {name} already exists in release {tag}")
        # GitHub rejects a second asset with the same name, so drop the old one.
        _request(
            f"{API}/repos/{owner}/{repo}/releases/assets/{asset['id']}",
            token,
            method="DELETE",
        )
        break

    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    data = path.read_bytes()
    uploaded = _request(
        f"{UPLOADS}/repos/{owner}/{repo}/releases/{release['id']}/assets?name={name}",
        token,
        method="POST",
        data=data,
        content_type=content_type,
    )
    if not isinstance(uploaded, dict) or not uploaded.get("browser_download_url"):
        raise SystemExit(f"upload of {name} returned no download url")
    return str(uploaded["browser_download_url"])
