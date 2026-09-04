#!/usr/bin/env python3
"""Fill site templates from environment / .env into an output directory.

Committed `site/` keeps `__AC_*__` placeholders. Default output is `dist/site`
(gitignored). Push that tree (or copy into your Pages repo) after render.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import settings  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_env_files() -> None:
    state = os.environ.get("AC_STATE", "").strip()
    candidates = []
    if state:
        candidates.append(Path(state) / ".env")
    candidates.extend([REPO / ".env", REPO / "compose" / ".env"])
    for path in candidates:
        load_dotenv(path)


def practice_car_list_html() -> str:
    from car_skins import PRACTICE_CARS, load_car_display_names

    names = load_car_display_names(REPO / "catalog")
    items = []
    for folder in PRACTICE_CARS:
        label = names.get(folder) or folder
        items.append(f"<li>{label}</li>")
    return "\n            ".join(items)


def practice_track_list_html() -> str:
    from content_manifest import PRACTICE_TRACKS

    items = []
    for item in PRACTICE_TRACKS:
        url = settings.release_track_url(item["folder"])
        items.append(f'<li><a href="{url}">{item["label"]}</a></li>')
    return "\n            ".join(items)


def substitute(text: str) -> str:
    mapping = {
        "__AC_PUBLIC_IP__": settings.public_ip(),
        "__AC_GITHUB_OWNER__": settings.github_owner(),
        "__AC_GITHUB_REPO__": settings.github_pages_repo(),
        "__AC_PAGES_URL__": settings.pages_url().rstrip("/"),
        "__AC_124_RELEASE_URL__": settings.release_124_url(),
        "__AC_JOIN_8081__": settings.join_url(8081),
        "__AC_JOIN_8082__": settings.join_url(8082),
        "__AC_JOIN_8083__": settings.join_url(8083),
        "__AC_JOIN_8089__": settings.join_url(8089),
        "__AC_DISCORD_INVITE__": settings.discord_invite_url(),
        "__AC_DISCORD_CHANNEL__": settings.discord_channel_url(),
        "__AC_DISCORD_FEATURE_REQUESTS__": settings.discord_feature_requests_url(),
        "__AC_CARS_LIST__": practice_car_list_html(),
        "__AC_TRACKS_LIST__": practice_track_list_html(),
    }
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def write_content_json(path: Path) -> None:
    from content_manifest import existing_car_version, write_content_json as write_manifest

    version = existing_car_version(REPO / "site" / "content.json") or "2.2"
    write_manifest(
        path,
        settings.github_owner(),
        settings.github_pages_repo(),
        car_version=version,
        car_url=settings.release_124_url(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "dist" / "site",
        help="Rendered output directory (default: dist/site)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite site/ templates (avoid for commits; use for Pages-only trees)",
    )
    args = parser.parse_args()
    load_env_files()
    if not settings.discord_invite_url():
        raise SystemExit(
            "DISCORD_INVITE_URL is not set. Run scripts/setup_discord.py and put the printed URL in .env."
        )

    src = REPO / "site"
    out = src if args.in_place else args.out
    if not args.in_place:
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(
            src,
            out,
            ignore=shutil.ignore_patterns(".git", "*.pyc", "__pycache__"),
        )

    for rel in ("index.html", "dev/index.html", "README.md"):
        path = out / rel
        if not path.is_file():
            continue
        path.write_text(substitute(path.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"wrote {path}")

    write_content_json(out / "content.json")
    write_content_json(out / "dev" / "content.json")

    if not args.in_place:
        car = REPO / "catalog" / "cars" / "abarth_124_2016.json"
        if car.is_file():
            data = json.loads(car.read_text(encoding="utf-8"))
            data["source"] = settings.release_124_url()
            rendered = out / "catalog" / "abarth_124_2016.json"
            rendered.parent.mkdir(parents=True, exist_ok=True)
            rendered.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {rendered}")


if __name__ == "__main__":
    main()
