#!/usr/bin/env python3
"""Publish a series' numbered skins as a bumped car zip so CM downloads them.

Runs after `generate_series_liveries.py`, against the same build content tree.
The car's `ui/ui_car.json` version gets a suffix derived from the pack contents,
so an unchanged roster republishes the same version (CM does nothing) and a
changed roster produces a new one (CM re-downloads).

Usage:
  py -3 scripts/publish_series_race_pack.py --series series-1 \
      --content /var/lib/ac-host/build/content --state /var/lib/ac-host/state
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _path in (str(REPO / "shared"), str(REPO / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import content_manifest  # noqa: E402
import github_release  # noqa: E402
import pack_content  # noqa: E402
import series_lib  # noqa: E402

BASE_VERSION_RE = re.compile(r"^(?P<base>[0-9][0-9A-Za-z.]*?)(?:-[a-z0-9]+-[0-9a-f]{6})?$")


def load_manifest(state: Path, series_id: str) -> dict:
    path = series_lib.series_state_dir(state, series_id) / "race_pack" / "manifest.json"
    if not path.is_file():
        raise SystemExit(f"no pack manifest at {path}; run generate_series_liveries.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def pack_fingerprint(manifest: dict) -> str:
    """Six hex chars over what a client would actually download.

    Derived from the skins rather than a counter, so republishing an unchanged
    roster is a no-op for every driver instead of a fresh 300 MB download.
    """
    drivers = sorted(
        (str(d.get("race_skin") or ""), str(d.get("sha256") or ""))
        for d in manifest.get("drivers") or []
    )
    digest = hashlib.sha256(json.dumps(drivers).encode("utf-8")).hexdigest()
    return digest[:6]


def base_version(version: str) -> str:
    """Strip a previous series suffix so versions do not accumulate them."""
    match = BASE_VERSION_RE.match(version.strip())
    return match.group("base") if match else version.strip()


def series_version(manifest: dict, current: str, series_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", series_id.lower())
    return f"{base_version(current)}-{slug}-{pack_fingerprint(manifest)}"


def set_ui_car_version(content: Path, car: str, version: str) -> str:
    """Write the version CM compares against; returns the previous value."""
    path = content / "cars" / car / "ui" / "ui_car.json"
    if not path.is_file():
        raise SystemExit(f"missing {path}; the build content tree needs the full car folder")
    # ui_car.json is frequently UTF-8 with a BOM and occasionally has trailing
    # nulls from the original mod, so read it forgivingly and write it back clean.
    raw = path.read_text(encoding="utf-8-sig", errors="replace").rstrip("\x00 \r\n\t")
    data = json.loads(raw)
    previous = str(data.get("version") or "")
    data["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", required=True)
    parser.add_argument("--state", type=Path, default=REPO / "STATE")
    parser.add_argument("--catalog", type=Path, default=REPO / "catalog")
    parser.add_argument(
        "--content",
        type=Path,
        required=True,
        help="Build content tree holding the FULL car folder (not the slim server content)",
    )
    parser.add_argument("--out", type=Path, default=None, help="Where to write the zip")
    parser.add_argument("--owner", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--token", default="", help="GitHub token (else env or secrets file)")
    parser.add_argument(
        "--content-json",
        type=Path,
        action="append",
        default=[],
        help="content.json to update; repeatable (e.g. prod and dev dist)",
    )
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(args.state, args.series)
    car = str(manifest.get("car") or "")
    drivers = manifest.get("drivers") or []
    if not car or not drivers:
        raise SystemExit("pack manifest has no car or no drivers")

    car_root = args.content / "cars" / car
    missing = [d["race_skin"] for d in drivers if not (car_root / "skins" / d["race_skin"]).is_dir()]
    if missing:
        raise SystemExit(
            f"{len(missing)} generated skins are not in {car_root / 'skins'}: "
            f"{', '.join(missing[:5])}"
        )

    import settings

    owner = args.owner or settings.github_owner()
    repo = args.repo or settings.github_pages_repo()
    if not owner or owner == "OWNER" or not repo:
        raise SystemExit("set AC_GITHUB_OWNER / AC_GITHUB_REPO or pass --owner/--repo")

    current = content_manifest.ui_car_version(args.content.parent, car) or ""
    version = series_version(manifest, current, args.series)
    previous = set_ui_car_version(args.content, car, version)
    print(f"{car}: ui_car.json version {previous or '(unset)'} -> {version}")
    print(f"pack: {len(drivers)} numbered skins ({manifest.get('generated_at')})")

    out_dir = args.out or (args.content.parent / "dist")
    out_dir.mkdir(parents=True, exist_ok=True)
    # pack_car takes the AC root (the parent of content/) and validates that the
    # zip's data.acd matches the source, which is the server's join checksum.
    zip_path = pack_content.pack_car(args.content.parent, car, out_dir, skip_check=True)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"zip: {zip_path} ({size_mb:.0f} MB)")

    url = ""
    if args.no_upload:
        print("skipped upload")
    else:
        token = github_release.load_token(args.token)
        url = github_release.upload_asset(
            owner, repo, content_manifest.RELEASE_TAG, zip_path, token
        )
        print(f"uploaded: {url}")

    for path in args.content_json:
        content_manifest.write_content_json(
            Path(path), owner, repo, car_versions={car: version}
        )

    pack_dir = series_lib.series_state_dir(args.state, args.series) / "race_pack"
    (pack_dir / "published.json").write_text(
        json.dumps(
            {
                "series_id": args.series,
                "car": car,
                "version": version,
                "previous_version": previous,
                "fingerprint": pack_fingerprint(manifest),
                "zip": str(zip_path),
                "zip_mb": round(size_mb, 1),
                "url": url,
                "drivers": len(drivers),
                "published_at": series_lib.utcnow(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"recorded: {pack_dir / 'published.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
