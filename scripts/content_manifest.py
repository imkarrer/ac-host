"""Shared CM content.json: hosted car + practice track zips on GitHub release `content`.

Do not put paid SIM TRAXX Autobahn here. details.py maps tracks[folder] →
content.track for that lobby's Download missing content.

Kunos base-game cars (Miata, Elise, E30) stay out of cars{} — joiners already
have them. CM only downloads ids that appear in content.cars.
"""

from __future__ import annotations

import json
from pathlib import Path

CAR = "abarth_124_2016"
RELEASE_TAG = "content"

# Hosted mods. version must match ui/ui_car.json in the zip.
DOWNLOADABLE_CARS = (
    {"id": "abarth_124_2016", "label": "Abarth 124 Spider", "version": "2.2"},
    {"id": "tbb_toyota_gr86_premium", "label": "Toyota GR86 Premium", "version": "2.0.1"},
    {"id": "pc_civic", "label": "Honda Civic Type-R (FK8)", "version": "1.02"},
    {"id": "some1_honda_nsx_1997_s1", "label": "Honda NSX NA2 S1 (1997)", "version": "3.0.0"},
)

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


def is_downloadable_car(folder: str) -> bool:
    return any(item["id"] == folder for item in DOWNLOADABLE_CARS)


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


def ui_car_version(root: Path, car: str) -> str | None:
    for path in (
        root / "content" / "cars" / car / "ui" / "ui_car.json",
        root / "cars" / car / "ui" / "ui_car.json",
    ):
        if not path.is_file():
            continue
        try:
            version = json.loads(path.read_text(encoding="utf-8")).get("version")
        except (OSError, json.JSONDecodeError):
            continue
        if version:
            return str(version).strip()
    return None


def existing_car_versions(*paths: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            cars = json.loads(path.read_text(encoding="utf-8")).get("cars") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(cars, dict):
            continue
        for folder, meta in cars.items():
            if isinstance(meta, dict) and meta.get("version"):
                out[str(folder)] = str(meta["version"]).strip()
    return out


def default_car_versions() -> dict[str, str]:
    return {item["id"]: str(item["version"]) for item in DOWNLOADABLE_CARS}


def resolve_car_versions(
    *paths: Path,
    overrides: dict[str, str] | None = None,
    content_root: Path | None = None,
) -> dict[str, str]:
    versions = default_car_versions()
    versions.update(existing_car_versions(*paths))
    if content_root:
        for item in DOWNLOADABLE_CARS:
            found = ui_car_version(content_root, item["id"])
            if found:
                versions[item["id"]] = found
    if overrides:
        for key, value in overrides.items():
            if value:
                versions[key] = str(value)
    return versions


def cars_payload(
    owner: str,
    repo: str,
    versions: dict[str, str],
    *,
    car_urls: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    urls = car_urls or {}
    return {
        item["id"]: {
            "url": urls.get(item["id"]) or release_asset_url(owner, repo, f"{item['id']}.zip"),
            "version": str(versions.get(item["id"]) or item["version"]),
        }
        for item in DOWNLOADABLE_CARS
    }


def content_payload(
    owner: str,
    repo: str,
    *,
    car_version: str | None = None,
    car_url: str | None = None,
    car_versions: dict[str, str] | None = None,
    content_root: Path | None = None,
    existing: Path | None = None,
) -> dict:
    overrides = dict(car_versions or {})
    if car_version:
        overrides[CAR] = car_version
    versions = resolve_car_versions(
        *([existing] if existing else []),
        overrides=overrides,
        content_root=content_root,
    )
    urls = {CAR: car_url} if car_url else None
    return {
        "cars": cars_payload(owner, repo, versions, car_urls=urls),
        "tracks": tracks_payload(owner, repo),
    }


def write_content_json(
    path: Path,
    owner: str,
    repo: str,
    *,
    car_version: str | None = None,
    car_url: str | None = None,
    car_versions: dict[str, str] | None = None,
    content_root: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content_payload(
        owner,
        repo,
        car_version=car_version,
        car_url=car_url,
        car_versions=car_versions,
        content_root=content_root,
        existing=path,
    )
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def existing_car_version(*paths: Path) -> str | None:
    versions = existing_car_versions(*paths)
    if versions.get(CAR):
        return versions[CAR]
    return None
