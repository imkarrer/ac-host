#!/usr/bin/env python3
"""Create a deploy key, write it into the Nix config, and install it on ac-box.

The live installer still accepts a password. This copies the pubkey over that
one-time password login, then later rebuilds keep the key and turn passwords off.

Examples (PowerShell):

  python scripts/bootstrap_ssh.py --host $env:AC_BOX_HOST --user $env:AC_BOX_USER
  python scripts/bootstrap_ssh.py --host 127.0.0.1 --user nixosuser --install-only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
KEYS_NIX = REPO / "hosts" / "ac-box" / "ssh-keys.local.nix"
COMMENT = os.environ.get("AC_DEPLOY_KEY_COMMENT", "ac-host-deploy")


def home_ssh() -> Path:
    return Path.home() / ".ssh"


def key_paths() -> tuple[Path, Path]:
    ssh_dir = home_ssh()
    return ssh_dir / "id_ed25519_ac-host", ssh_dir / "id_ed25519_ac-host.pub"


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=True, **kwargs)


def ensure_key() -> str:
    priv, pub = key_paths()
    priv.parent.mkdir(mode=0o700, exist_ok=True)
    if not pub.is_file():
        run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(priv),
                "-N",
                "",
                "-C",
                COMMENT,
            ]
        )
    key = pub.read_text(encoding="utf-8").strip()
    if not key.startswith("ssh-"):
        raise SystemExit(f"refusing to use {pub}: not an OpenSSH public key")
    return key


def extra_pubkeys() -> list[str]:
    sk = home_ssh() / "id_ed25519_sk.pub"
    if not sk.is_file():
        return []
    line = sk.read_text(encoding="utf-8").strip()
    return [line] if line else []


def nix_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_keys_nix(keys: list[str]) -> None:
    unique: list[str] = []
    for key in keys:
        if key and key not in unique:
            unique.append(key)
    body = "\n".join(f'  "{nix_escape(key)}"' for key in unique)
    KEYS_NIX.write_text(f"[\n{body}\n]\n", encoding="utf-8")
    print(f"wrote {KEYS_NIX} ({len(unique)} keys)", file=sys.stderr)


def upsert_ssh_config(host: str, user: str, identity: Path) -> None:
    config_path = home_ssh() / "config"
    block = "\n".join(
        [
            "Host ac-box",
            f"  HostName {host}",
            f"  User {user}",
            f"  IdentityFile {identity}",
            "  IdentitiesOnly yes",
            "",
        ]
    )
    existing = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    marker = "Host ac-box"
    if marker in existing:
        lines = existing.splitlines(keepends=True)
        out: list[str] = []
        skipping = False
        for line in lines:
            if line.startswith("Host ") and skipping:
                skipping = False
            if line.startswith(marker):
                skipping = True
                continue
            if skipping:
                continue
            out.append(line)
        existing = "".join(out).rstrip() + ("\n\n" if out else "")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(existing + block, encoding="utf-8")
    print(f"wrote {config_path} Host ac-box -> {user}@{host}", file=sys.stderr)


def remote_install(host: str, user: str, pubkey: str) -> None:
    priv, _ = key_paths()
    remote = f"""
set -eu
umask 077
mkdir -p "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 700 "$HOME/.ssh"
chmod 600 "$HOME/.ssh/authorized_keys"
if ! grep -Fqx {repr(pubkey)} "$HOME/.ssh/authorized_keys"; then
  printf '%s\\n' {repr(pubkey)} >> "$HOME/.ssh/authorized_keys"
fi
if command -v sudo >/dev/null 2>&1; then
  sudo mkdir -p /root/.ssh
  sudo touch /root/.ssh/authorized_keys
  sudo chmod 700 /root/.ssh
  sudo chmod 600 /root/.ssh/authorized_keys
  if ! sudo grep -Fqx {repr(pubkey)} /root/.ssh/authorized_keys; then
    printf '%s\\n' {repr(pubkey)} | sudo tee -a /root/.ssh/authorized_keys >/dev/null
  fi
fi
echo installed-ok
"""
    cmd = [
        "ssh",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive,publickey",
        "-o",
        "PubkeyAuthentication=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(priv),
        f"{user}@{host}",
        "sh",
        "-s",
    ]
    print(
        f"copying pubkey to {user}@{host} (type the installer password if asked)",
        file=sys.stderr,
    )
    run(cmd, input=remote, text=True)


def fetch_hardware(host: str, user: str) -> None:
    dest = REPO / "hosts" / "ac-box" / "hardware-configuration.nix"
    cmd = [
        "ssh",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(key_paths()[0]),
        f"{user}@{host}",
        "cat /etc/nixos/hardware-configuration.nix",
    ]
    print("+", " ".join(cmd), file=sys.stderr)
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            "could not pull hardware-configuration.nix yet (ok if this is still the installer password step)",
            file=sys.stderr,
        )
        print(result.stderr, file=sys.stderr)
        return
    if "fileSystems" not in result.stdout:
        print("remote hardware-configuration.nix looked empty; not overwriting stub", file=sys.stderr)
        return
    dest.write_text(result.stdout, encoding="utf-8")
    print(f"wrote {dest}", file=sys.stderr)


def verify(host: str, user: str) -> None:
    priv, _ = key_paths()
    run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-i",
            str(priv),
            f"{user}@{host}",
            "echo key-login-ok && hostname && whoami",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("AC_BOX_HOST", "127.0.0.1"))
    parser.add_argument("--user", default=os.environ.get("AC_BOX_USER", "nixosuser"))
    parser.add_argument(
        "--install-only",
        action="store_true",
        help="Only copy the key over SSH; do not rewrite ssh-keys.local.nix",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Write the key into Nix + SSH config; do not connect",
    )
    args = parser.parse_args()

    pubkey = ensure_key()
    if not args.install_only:
        write_keys_nix([pubkey, *extra_pubkeys()])
        upsert_ssh_config(args.host, args.user, key_paths()[0])
    if args.local_only:
        return
    remote_install(args.host, args.user, pubkey)
    verify(args.host, args.user)
    fetch_hardware(args.host, args.user)
    print(f"SSH ready: ssh ac-box   (or {args.user}@{args.host})")


if __name__ == "__main__":
    main()
