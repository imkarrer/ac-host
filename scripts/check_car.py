#!/usr/bin/env python3
"""Fail a car before it reaches the lobby.

Vanilla AC DX11 and BlurredObjects abort on problems Content Manager will
still zip. Run this on the Steam car folder before pack/deploy:

    python scripts/check_car.py tbb_toyota_gr86_premium
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

DDS_MAGIC = b"DDS "
ACD_KEY_CHARS = set(b"0123456789-")
HEADER_GUESSES = (
    b"[HEADER]\n",
    b"[HEADER]\r\n",
)


@dataclass(frozen=True)
class Issue:
    level: str
    where: str
    message: str


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _read_str(data: bytes, off: int) -> tuple[bytes, int]:
    n = _u32(data, off)
    return data[off + 4 : off + 4 + n], off + 4 + n


def parse_dds(blob: bytes) -> dict | None:
    if len(blob) < 128 or blob[:4] != DDS_MAGIC:
        return None
    flags, height, width, pitch, depth, mips = struct.unpack_from("<IIIIII", blob, 8)
    pf_flags, fourcc = struct.unpack_from("<I4s", blob, 80)
    return {
        "flags": flags,
        "w": width,
        "h": height,
        "pitch": pitch,
        "depth": depth,
        "mips": mips,
        "pf_flags": pf_flags,
        "fourcc": fourcc,
    }


def check_kn5_textures(path: Path) -> list[Issue]:
    data = path.read_bytes()
    if data[:6] != b"sc6969":
        return [Issue("error", path.name, "not a kn5")]
    off = 10
    ver = _u32(data, 6)
    if ver > 5:
        off = 14
    ntex = _u32(data, off)
    off += 4
    issues: list[Issue] = []
    for _ in range(ntex):
        off += 4
        name, off = _read_str(data, off)
        size = _u32(data, off)
        off += 4
        blob = data[off : off + size]
        off += size
        label = f"{path.name}:{name.decode('ascii', 'replace')}"
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            continue
        info = parse_dds(blob)
        if info is None:
            issues.append(Issue("error", label, "packed texture is not DDS or PNG"))
            continue
        fourcc = info["fourcc"]
        w, h = info["w"], info["h"]
        if fourcc == b"DX10":
            issues.append(
                Issue(
                    "error",
                    label,
                    f"{w}x{h} DX10/BC7 — vanilla AC DX11 crashes in KGLTexture::initSize",
                )
            )
            continue
        if fourcc in (b"DXT1", b"DXT3", b"DXT5"):
            if w < 4 or h < 4 or w % 4 or h % 4:
                issues.append(
                    Issue(
                        "error",
                        label,
                        f"{w}x{h} {fourcc.decode()} — D3DX11 requires multiples of 4",
                    )
                )
    return issues


def kn5_has_node(data: bytes, name: str) -> bool:
    raw = name.encode("ascii")
    return struct.pack("<I", len(raw)) + raw in data


def parse_acd(data: bytes) -> list[tuple[str, bytes]]:
    off = 0
    files: list[tuple[str, bytes]] = []
    while off + 8 <= len(data):
        nlen = _u32(data, off)
        if not 1 <= nlen <= 256 or off + 4 + nlen + 4 > len(data):
            break
        off += 4
        name = data[off : off + nlen].decode("ascii", "replace")
        off += nlen
        dlen = _u32(data, off)
        off += 4
        end = off + dlen * 4
        if end > len(data):
            break
        packed = bytes(_u32(data, off + 4 * i) & 0xFF for i in range(dlen))
        off = end
        files.append((name, packed))
    return files


def _decrypt(packed: bytes, key: bytes) -> bytes:
    return bytes((packed[i] - key[i % len(key)]) % 256 for i in range(len(packed)))


def _mostly_text(blob: bytes) -> bool:
    if not blob:
        return False
    return sum(c in (9, 10, 13) or 32 <= c < 127 for c in blob) / len(blob) > 0.85


def recover_acd_key(files: list[tuple[str, bytes]]) -> bytes | None:
    packed = next((p for n, p in files if n.endswith(".ini") and p), None)
    if packed is None:
        return None
    tails = (
        b"",
        b"\n",
        b"\r\n",
        b"\n\n",
        b"\r\n\r\n",
        b"\n\n[VIRTUALKM]\n",
        b"\n\n[INFO]\n",
        b"\r\n\r\n[VIRTUALKM]\r\n",
        b"\r\n\r\n[INFO]\r\n",
    )
    for header in HEADER_GUESSES:
        for ver in range(1, 16):
            for extra in tails:
                plain = header + b"VERSION=" + str(ver).encode() + extra
                if len(plain) > len(packed):
                    continue
                stream = bytes((packed[i] - plain[i]) % 256 for i in range(len(plain)))
                if not stream or not set(stream) <= ACD_KEY_CHARS:
                    continue
                for length in range(16, min(40, len(stream) + 1)):
                    key = stream[:length]
                    out = _decrypt(packed, key)
                    if out.startswith(b"[HEADER]") and _mostly_text(out[:200]):
                        return key
    return None


def read_data_file(car: Path, name: str) -> bytes | None:
    loose = car / "data" / name
    if loose.is_file():
        return loose.read_bytes()
    acd = car / "data.acd"
    if not acd.is_file():
        return None
    files = parse_acd(acd.read_bytes())
    packed = next((p for n, p in files if n == name), None)
    if packed is None:
        return None
    if name.endswith(".ini") and (packed.startswith(b"[") or packed.startswith(b";") or packed[:1] in (b"\n", b"\r")):
        return packed
    key = recover_acd_key(files)
    if key is None:
        return None
    return _decrypt(packed, key)


def check_blurred_objects(car: Path) -> list[Issue]:
    raw = read_data_file(car, "blurred_objects.ini")
    if raw is None:
        return []
    names: list[str] = []
    for line in raw.decode("ascii", "replace").splitlines():
        if line.strip().upper().startswith("NAME="):
            names.append(line.split("=", 1)[1].strip())
    if not names:
        return []
    kn5s = sorted(p for p in car.glob("*.kn5") if p.name != "collider.kn5")
    if not kn5s:
        return [Issue("error", "blurred_objects.ini", "no car kn5 to match node names")]
    blobs = [p.read_bytes() for p in kn5s]
    issues: list[Issue] = []
    for name in names:
        if not any(kn5_has_node(blob, name) for blob in blobs):
            issues.append(
                Issue(
                    "error",
                    "blurred_objects.ini",
                    f"object {name} is missing from the kn5 — AC crashes in BlurredObjects",
                )
            )
    return issues


def check_folder(car: Path) -> list[Issue]:
    if not car.is_dir():
        return [Issue("error", str(car), "missing car folder")]
    issues: list[Issue] = []
    kn5s = sorted(car.glob("*.kn5"))
    if not kn5s:
        issues.append(Issue("error", car.name, "no kn5 files"))
    for kn5 in kn5s:
        issues.extend(check_kn5_textures(kn5))
    issues.extend(check_blurred_objects(car))
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("car", help="Folder name under content/cars")
    parser.add_argument(
        "--ac-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Assetto Corsa install (parent of ac-host/)",
    )
    args = parser.parse_args()
    car = args.ac_root / "content" / "cars" / args.car
    issues = check_folder(car)
    for item in issues:
        print(f"{item.level.upper()}: {item.where}: {item.message}")
    errors = sum(1 for item in issues if item.level == "error")
    if errors:
        print(f"{errors} error(s) — do not pack or deploy this car")
        raise SystemExit(1)
    print(f"ok {car.name}")


if __name__ == "__main__":
    main()
