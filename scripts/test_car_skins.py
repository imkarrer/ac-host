#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bot"))

import car_skins  # noqa: E402


class CarSkinsTests(unittest.TestCase):
    def test_list_signup_skins_gr86_factory_only(self) -> None:
        content = REPO.parent / "content"
        car = "tbb_toyota_gr86_premium"
        if not (content / "cars" / car).is_dir():
            self.skipTest("GR86 not installed locally")
        skins = car_skins.list_signup_skins(content, car)
        folders = [folder for folder, _ in skins]
        self.assertIn("04_trueno_blue", folders)
        self.assertNotIn("Neptune 2.0", folders)
        labels = dict(skins)
        self.assertEqual(labels["04_trueno_blue"], "Trueno Blue")


if __name__ == "__main__":
    unittest.main()
