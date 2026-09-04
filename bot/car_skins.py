"""Shared car/skin listing from catalog + content tree (no Discord)."""

from __future__ import annotations

import json
from pathlib import Path

# Cars allowed on practice lobbies (union of static track catalogs).
PRACTICE_CARS = [
    "abarth_124_2016",
    "tbb_toyota_gr86_premium",
    "pc_civic",
    "ks_mazda_miata",
    "lotus_elise_sc",
    "bmw_m3_e30",
]


def load_car_display_names(catalog: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    cars = catalog / "cars"
    if not cars.is_dir():
        return names
    for path in cars.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        folder = str(data.get("folder") or path.stem)
        names[folder] = str(data.get("displayName") or folder)
    return names


def list_skins(content: Path, car: str) -> list[str]:
    skins = content / "cars" / car / "skins"
    if not skins.is_dir():
        return []
    names = []
    for path in sorted(skins.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if "owner_white" in path.name.lower():
            continue
        if (
            (path / "ui_skin.json").is_file()
            or (path / "preview.jpg").is_file()
            or (path / "skin.ini").is_file()
        ):
            names.append(path.name)
    return names


def list_practice_cars(content: Path, catalog: Path | None = None) -> list[tuple[str, str]]:
    """Return (folder_id, display_name) for cars that exist under content/cars."""
    display = load_car_display_names(catalog) if catalog else {}
    out: list[tuple[str, str]] = []
    for car in PRACTICE_CARS:
        if not (content / "cars" / car).is_dir():
            continue
        out.append((car, display.get(car) or car))
    return out


def load_livery_reservations(whitelist_path: Path) -> list[dict[str, str]]:
    """Enabled players with a single {car, skin} preference → reserved pits."""
    if not whitelist_path.is_file():
        return []
    try:
        data = json.loads(whitelist_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    prefs: list[dict[str, str]] = []
    for player in data.get("players") or []:
        if not player.get("enabled", True):
            continue
        steam = str(player.get("steam_id") or "").strip()
        livery = player.get("livery")
        if not steam or not isinstance(livery, dict):
            continue
        car = str(livery.get("car") or "").strip()
        skin = str(livery.get("skin") or "").strip()
        if not car or not skin:
            continue
        prefs.append({"steam_id": steam, "car": car, "skin": skin})
    return prefs
