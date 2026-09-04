"""Shared CM content.json: 124 zip + practice track zips on GitHub release `content`.

Do not put paid SIM TRAXX Autobahn here. details.py maps tracks[folder] →
content.track for that lobby's Download missing content.
"""

from __future__ import annotations

import json
from pathlib import Path

CAR = "abarth_124_2016"
RELEASE_TAG = "content"

# Hosted free OverTake packs. version must match ui_track.json in the zip.
PRACTICE_TRACKS = (
    {
        "id": "blackhawk",
        "folder": "slipangle_ggt",
        "label": "Blackhawk",
        "version": "1.1.1",
    },
    {
        "id": "road-america",
        "folder": "lilski_road_america",
        "label": "Road America",
        "version": "1.0",
    },
    {
        "id": "gingerman",
        "folder": "gingerman_raceway",
        "label": "Gingerman",
        "version": "1.0",
    },
)


def release_asset_url(owner: str, repo: str, filename: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{RELEASE_TAG}/{filename}"


def release_track_url(owner: str, repo: str, folder: str) -> str:
    return release_asset_url(owner, repo, f"{folder}.zip")


def tracks_payload(owner: str, repo: str) -> dict[str, dict[str, str]]:
    return {
        item["folder"]: {
            "url": release_track_url(owner, repo, item["folder"]),
            "version": str(item["version"]),
        }
        for item in PRACTICE_TRACKS
    }


def content_payload(
    owner: str,
    repo: str,
    *,
    car_version: str,
    car_url: str | None = None,
) -> dict:
    return {
        "cars": {
            CAR: {
                "url": car_url or release_asset_url(owner, repo, f"{CAR}.zip"),
                "version": str(car_version),
            }
        },
        "tracks": tracks_payload(owner, repo),
    }


def write_content_json(
    path: Path,
    owner: str,
    repo: str,
    *,
    car_version: str,
    car_url: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content_payload(owner, repo, car_version=car_version, car_url=car_url)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def existing_car_version(*paths: Path) -> str | None:
    for path in paths:
        if not path.is_file():
            continue
        try:
            version = (
                json.loads(path.read_text(encoding="utf-8"))
                .get("cars", {})
                .get(CAR, {})
                .get("version")
            )
        except (OSError, json.JSONDecodeError):
            continue
        if version:
            return str(version).strip()
    return None
