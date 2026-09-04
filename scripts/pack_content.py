#!/usr/bin/env python3
"""Build CM-installable zips (root entry = car or track folder name).

One zip per folder. Brainerd layouts stay in gb_brainerd — that is one asset.
Do not stuff the 124 and both tracks into one archive: CM Online downloads
the car URL and this lobby's track URL separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

SKIP_DIR_NAMES = {"_extract", "__pycache__", "_paint_report"}
SKIP_FILE_NAMES = {
    "_patch_stripe_meshes.py",
    "_patch_lcd_mph.py",
    "_patch_speedo_160mph.py",
    "_patch_disable_cmpaint.py",
    "_patch_forza_paint_mats.py",
    "_bake_online_paint.py",
    "_bake_skin_dds.py",
    "_bake_dxt1_skins.py",
    "_bake_dxt5_online.py",
    "_dump_carpaint.py",
    "_rank_mats.py",
    "_nuke_black_paint.py",
    "_restore_red_accents.py",
    "_restore_black_trim.py",
    "_rename_carpaint.py",
    "_rank_paint_meshes.py",
    "_dump_carpaint_live.py",
    "_fix_bianco_multimap.py",
    "_bake_skin_color.py",
    "_body_metal_detail.dds",
    "data.acd.bak",
}
SKIP_SUFFIXES = {".bak", ".bak_stripe", ".bak_lcd", ".bak_speedo", ".bak_dx11", ".bak_blur", ".bak_trim", ".bak_rename", ".bak_bianco"}
# kn5/dds/jpg barely shrink; store them so a 1.6 GB track zip finishes in minutes.
STORE_SUFFIXES = {
    ".kn5",
    ".dds",
    ".png",
    ".jpg",
    ".jpeg",
    ".ogg",
    ".wav",
    ".mp3",
    ".bank",
    ".7z",
    ".zip",
}

DEFAULT_CARS = ("abarth_124_2016", "tbb_toyota_gr86_premium", "pc_civic")
DEFAULT_TRACKS = ("slipangle_ggt", "gb_brainerd")
CM_RELEASES_API = "https://api.github.com/repos/gro-ove/actools/releases/latest"
CM_ZIP_NAME = "Content.Manager.zip"
HTTP_HEADERS = {
    "User-Agent": "ac-host-content-pack",
    "Accept": "application/vnd.github+json",
}


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIR_NAMES for part in rel.parts):
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if ".bak" in path.name:
        return True
    return any(path.name.endswith(suf) for suf in SKIP_SUFFIXES)


def pack_folder(src: Path, zip_path: Path) -> None:
    if not src.is_dir():
        raise SystemExit(f"missing folder: {src}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    folder_id = src.name
    files = [p for p in src.rglob("*") if p.is_file() and not should_skip(p, src)]
    files.sort()
    tmp = zip_path.with_suffix(zip_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for path in files:
            arcname = f"{folder_id}/{path.relative_to(src).as_posix()}"
            compress = (
                zipfile.ZIP_STORED
                if path.suffix.lower() in STORE_SUFFIXES
                else zipfile.ZIP_DEFLATED
            )
            zf.write(path, arcname=arcname, compress_type=compress)
    tmp.replace(zip_path)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"wrote {zip_path} ({size_mb:.1f} MB, {len(files)} files)")


def assert_zip_data_matches_source(src: Path, zip_path: Path) -> None:
    """Server checksum is the car's data.acd. The zip must contain that exact file."""
    acd = src / "data.acd"
    if not acd.is_file():
        return
    src_hash = hashlib.sha256(acd.read_bytes()).hexdigest()
    inner = f"{src.name}/data.acd"
    with zipfile.ZipFile(zip_path) as zf:
        if inner not in zf.namelist():
            raise SystemExit(f"{zip_path.name} missing {inner}")
        zip_hash = hashlib.sha256(zf.read(inner)).hexdigest()
    if src_hash != zip_hash:
        raise SystemExit(
            f"checksum mismatch {src.name} data.acd source={src_hash} zip={zip_hash}"
        )
    print(f"checksum {src.name} data.acd {src_hash[:12]}")


def car_requires_csp(car: str) -> bool:
    catalog = Path(__file__).resolve().parents[1] / "catalog" / "cars" / f"{car}.json"
    if not catalog.is_file():
        return False
    return bool(json.loads(catalog.read_text(encoding="utf-8")).get("requiresCsp"))


def pack_car(ac_root: Path, car: str, out_dir: Path, *, skip_check: bool = False) -> Path:
    src = ac_root / "content" / "cars" / car
    if not skip_check and car_requires_csp(car):
        print(f"skip check_car for {car} (requires Custom Shaders Patch)")
        skip_check = True
    if not skip_check:
        from check_car import check_folder

        issues = check_folder(src)
        for item in issues:
            print(f"{item.level.upper()}: {item.where}: {item.message}")
        if any(item.level == "error" for item in issues):
            raise SystemExit(f"check_car failed for {car}; fix or pass --skip-check")
    dest = out_dir / f"{car}.zip"
    pack_folder(src, dest)
    assert_zip_data_matches_source(src, dest)
    return dest


def pack_track(ac_root: Path, folder: str, out_dir: Path) -> Path:
    src = ac_root / "content" / "tracks" / folder
    dest = out_dir / f"{folder}.zip"
    pack_folder(src, dest)
    return dest


def content_manager_asset_url(release: dict) -> str:
    for asset in release.get("assets") or []:
        if asset.get("name") == CM_ZIP_NAME and asset.get("browser_download_url"):
            return str(asset["browser_download_url"])
    raise SystemExit("GitHub latest release has no Content.Manager.zip")


def fetch_content_manager(out_dir: Path) -> Path:
    """Official Lite zip from gro-ove/actools. Do not pack a local CM install."""
    req = urllib.request.Request(CM_RELEASES_API, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.loads(resp.read().decode("utf-8"))
    url = content_manager_asset_url(release)
    tag = release.get("tag_name") or ""
    dest = out_dir / CM_ZIP_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    zip_req = urllib.request.Request(url, headers={"User-Agent": HTTP_HEADERS["User-Agent"]})
    with urllib.request.urlopen(zip_req, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"wrote {dest} ({size_mb:.1f} MB, GitHub {tag})")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ac-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Assetto Corsa install (parent of ac-host/)",
    )
    parser.add_argument("--car", action="append", default=[], help="Car folder under content/cars")
    parser.add_argument(
        "--track",
        action="append",
        default=[],
        help="Track folder under content/tracks",
    )
    parser.add_argument("--all", action="store_true", help="Pack the 124, GR86, Gray Ghost, Brainerd, and fetch CM")
    parser.add_argument(
        "--cm",
        action="store_true",
        help="Download official Content.Manager.zip (GitHub Lite release)",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Do not run scripts/check_car.py before zipping a car",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: ac-host/dist)",
    )
    args = parser.parse_args()
    out = args.out or (Path(__file__).resolve().parents[1] / "dist")
    cars = list(args.car)
    tracks = list(args.track)
    fetch_cm = args.cm
    if args.all or (not cars and not tracks and not args.cm):
        cars = list(dict.fromkeys([*DEFAULT_CARS, *cars]))
        tracks = list(dict.fromkeys([*DEFAULT_TRACKS, *tracks]))
        fetch_cm = True
    if not cars and not tracks and not fetch_cm:
        raise SystemExit("nothing to pack; pass --car, --track, --cm, or --all")
    if fetch_cm:
        fetch_content_manager(out)
    for car in cars:
        pack_car(args.ac_root, car, out, skip_check=args.skip_check)
    for folder in tracks:
        pack_track(args.ac_root, folder, out)


if __name__ == "__main__":
    main()
