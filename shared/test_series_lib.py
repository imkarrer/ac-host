import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import series_lib


class ImportQualiLapsFromLeaderboardTests(unittest.TestCase):
    def test_reads_matching_lobby_by_car(self) -> None:
        with TemporaryDirectory() as raw:
            state_root = Path(raw)
            lobby_id = series_lib.quali_lobby_id("gt-cup", "r1")
            (state_root / "leaderboard.json").write_text(
                """{"lobbies": {"%s": {"allTime": [
                    {"guid": "1", "car": "abarth_124_2016", "ms": 91234},
                    {"guid": "2", "car": "abarth_124_2016", "ms": 88000},
                    {"guid": "3", "car": "other_car", "ms": 1000}
                ]}}}"""
                % lobby_id,
                encoding="utf-8",
            )
            laps = series_lib.import_quali_laps_from_leaderboard(
                state_root, "gt-cup", "r1", car="abarth_124_2016"
            )
            self.assertEqual(laps, {"1": 91234, "2": 88000})

    def test_missing_leaderboard_returns_empty(self) -> None:
        with TemporaryDirectory() as raw:
            state_root = Path(raw)
            laps = series_lib.import_quali_laps_from_leaderboard(
                state_root, "gt-cup", "r1", car="abarth_124_2016"
            )
            self.assertEqual(laps, {})

    def test_corrupt_leaderboard_warns_and_returns_empty_not_crash(self) -> None:
        # sync_quali_laps_to_round merges this into existing quali_laps
        # (best lap wins, never replaces), so a corrupt board must degrade
        # to "no new laps imported" rather than crash the round-sync task.
        with TemporaryDirectory() as raw:
            state_root = Path(raw)
            (state_root / "leaderboard.json").write_text("{not valid json", encoding="utf-8")
            with patch("sys.stderr"):
                laps = series_lib.import_quali_laps_from_leaderboard(
                    state_root, "gt-cup", "r1", car="abarth_124_2016"
                )
            self.assertEqual(laps, {})


if __name__ == "__main__":
    unittest.main()
