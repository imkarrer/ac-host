#!/usr/bin/env python3
"""Push series standings JSON to GitHub Pages (site/series/<id>.json)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "shared"))
sys.path.insert(0, str(REPO / "scripts"))

import series_lib  # noqa: E402
import settings  # noqa: E402

SIDECAR = REPO / "sidecar"
if str(SIDECAR) not in sys.path:
    sys.path.insert(0, str(SIDECAR))
from push_status import StatusPusher  # noqa: E402


def state_root() -> Path:
    raw = os.environ.get("AC_STATE", "").strip()
    if raw:
        return Path(raw)
    return REPO / "state"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series_id", nargs="?", default="series-1")
    parser.add_argument("--catalog", type=Path, default=REPO / "catalog")
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="Also write local copy under dist/site")
    args = parser.parse_args()

    root = args.state or state_root()
    catalog = args.catalog
    pages = settings.pages_url().rstrip("/")

    payload_path = series_lib.write_page_payload(root, catalog, args.series_id, pages_url=pages)
    text = payload_path.read_text(encoding="utf-8")

    out_local = args.out or (REPO / "dist" / "site" / "series" / f"{args.series_id}.json")
    out_local.parent.mkdir(parents=True, exist_ok=True)
    out_local.write_text(text, encoding="utf-8")
    print(f"wrote {out_local}")

    gh_path = os.environ.get("GITHUB_SERIES_PATH", f"series/{args.series_id}.json").strip().lstrip("/")
    os.environ["GITHUB_STATUS_PATH"] = gh_path

    pusher = StatusPusher()
    if pusher.enabled:
        pusher.flush_now(text)
        print(f"pushed -> {pusher.repo}:{pusher.branch}/{gh_path}")
    else:
        print("GITHUB_STATUS_TOKEN not set — local write only")


if __name__ == "__main__":
    main()
