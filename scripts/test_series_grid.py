"""Tests for series quali → grid → entry_list pipeline."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "shared"))
sys.path.insert(0, str(REPO / "scripts"))

import series_lib  # noqa: E402
from render_cfg import series_entry_list, series_server_cfg  # noqa: E402


class GridFromQualiTests(unittest.TestCase):
    def test_fastest_first_missed_back(self) -> None:
        signups = {
            "drivers": [
                {"steam_id": "111", "name": "Alice"},
                {"steam_id": "222", "name": "Bob"},
                {"steam_id": "333", "name": "Cara"},
            ]
        }
        quali = {"222": 91000, "111": 90000}
        grid = series_lib.grid_from_quali(signups, quali)
        self.assertEqual([row["steam_id"] for row in grid], ["111", "222", "333"])
        self.assertEqual(grid[0]["pos"], 1)
        self.assertIsNone(grid[2]["qual_time_ms"])

    def test_lock_grid_writes_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = REPO / "catalog"
            series_id = "series-1"
            round_id = "r00"
            series_lib.init_series_state(root, catalog, series_id)
            series_lib.signup_driver(
                root,
                catalog,
                series_id,
                steam_id="76561198000000001",
                discord_id="1",
                name="Alice",
            )
            series_lib.signup_driver(
                root,
                catalog,
                series_id,
                steam_id="76561198000000002",
                discord_id="2",
                name="Bob",
            )
            rnd = series_lib.load_round(root, series_id, round_id)
            series_lib.set_round_status(rnd, "open")
            series_lib.save_round(root, series_id, round_id, rnd)
            rnd = series_lib.load_round(root, series_id, round_id)
            series_lib.set_round_status(rnd, "quali")
            rnd["quali_laps"] = {"76561198000000002": 91234, "76561198000000001": 90100}
            series_lib.save_round(root, series_id, round_id, rnd)
            grid = series_lib.lock_grid_from_quali(root, catalog, series_id, round_id)
            self.assertEqual(grid[0]["steam_id"], "76561198000000001")
            saved = series_lib.load_round(root, series_id, round_id)
            self.assertEqual(saved["status"], "grid_locked")
            self.assertEqual(len(saved["grid"]), 2)


class SeriesEntryListTests(unittest.TestCase):
    def test_car_order_is_grid_order(self) -> None:
        drivers = [
            {"steam_id": "76561198000000001", "name": "Pole", "car": "tbb_toyota_gr86_premium", "skin": "04_trueno_blue"},
            {"steam_id": "76561198000000002", "name": "P2", "car": "tbb_toyota_gr86_premium", "skin": "06_steel"},
        ]
        text = series_entry_list(drivers)
        self.assertIn("[CAR_0]", text)
        self.assertIn("[CAR_1]", text)
        pole_idx = text.index("76561198000000001")
        p2_idx = text.index("76561198000000002")
        self.assertLess(pole_idx, p2_idx)
        self.assertIn("GUID=76561198000000001", text)


class SeriesServerCfgTests(unittest.TestCase):
    def test_race_only_skips_quali(self) -> None:
        track = {"folder": "slipangle_ggt", "layout": "", "cars": ["tbb_toyota_gr86_premium"], "maxClients": 24}
        text = series_server_cfg(
            name="Test",
            track=track,
            car="tbb_toyota_gr86_premium",
            mode="race-only",
            udp=9604,
            tcp=9604,
            http=8085,
            auth="127.0.0.1:18080",
            admin_password="x",
            max_clients=10,
            race_minutes=20,
        )
        self.assertIn("LOCKED_ENTRY_LIST=1", text)
        self.assertIn("[QUALIFY]", text)
        self.assertIn("TIME=0", text)
        self.assertIn("TIME=20", text)


if __name__ == "__main__":
    unittest.main()
