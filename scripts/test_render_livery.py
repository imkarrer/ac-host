"""Unit tests for GUID-reserved livery pits in entry_list."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import render_cfg


class EntryListReservationTests(unittest.TestCase):
    def test_reserved_guid_pit_comes_first(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            content = Path(raw)
            skin = content / "cars" / "abarth_124_2016" / "skins" / "01_Nero"
            skin.mkdir(parents=True)
            (skin / "preview.jpg").write_bytes(b"x")
            bianco = content / "cars" / "abarth_124_2016" / "skins" / "02_Bianco"
            bianco.mkdir(parents=True)
            (bianco / "preview.jpg").write_bytes(b"x")
            text = render_cfg.entry_list(
                ["abarth_124_2016"],
                3,
                skin_mode="pinned",
                content=content,
                reservations=[
                    {
                        "steam_id": "76561197961983498",
                        "car": "abarth_124_2016",
                        "skin": "01_Nero",
                    }
                ],
            )
        self.assertIn("GUID=76561197961983498", text)
        self.assertIn("SKIN=01_Nero", text)
        # First block is the reservation
        first = text.split("\n\n")[0]
        self.assertIn("GUID=76561197961983498", first)
        self.assertIn("SKIN=01_Nero", first)

    def test_cycle_gives_distinct_skins_per_model(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            content = Path(raw)
            car = content / "cars" / "abarth_124_2016" / "skins"
            for name in ("00_Rosso", "01_Nero", "02_Bianco", "07_Giallo"):
                d = car / name
                d.mkdir(parents=True)
                (d / "preview.jpg").write_bytes(b"x")
            text = render_cfg.entry_list(
                ["abarth_124_2016", "ks_mazda_miata"],
                8,
                skin_mode="cycle",
                content=content,
                reservations=[],
            )
        skins_124: list[str] = []
        for block in text.strip().split("\n\n"):
            if "MODEL=abarth_124_2016" not in block:
                continue
            for line in block.splitlines():
                if line.startswith("SKIN="):
                    skins_124.append(line.split("=", 1)[1])
        self.assertGreaterEqual(len(skins_124), 4)
        self.assertEqual(len(set(skins_124[:4])), 4)


if __name__ == "__main__":
    unittest.main()
