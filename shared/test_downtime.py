import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import downtime

CT = ZoneInfo("America/Chicago")


class ScheduleTests(unittest.TestCase):
    def test_next_restart_from_evening_is_3am(self) -> None:
        now = datetime(2026, 9, 4, 19, 0, 0, tzinfo=CT)
        with patch.dict(os.environ, {"PRACTICE_RESTART_AT": "03:00", "AC_TZ": "America/Chicago"}):
            nxt = downtime.next_restart(now)
            assert nxt is not None
            self.assertEqual(nxt.hour, 3)
            self.assertEqual(nxt.day, 5)
            self.assertEqual(int(downtime.seconds_until_restart(now) or 0), 8 * 3600)
            self.assertEqual(downtime.practice_time_minutes(now), 480)

    def test_at_exactly_3am_uses_tomorrow(self) -> None:
        now = datetime(2026, 9, 5, 3, 0, 0, tzinfo=CT)
        with patch.dict(os.environ, {"PRACTICE_RESTART_AT": "03:00", "AC_TZ": "America/Chicago"}):
            nxt = downtime.next_restart(now)
            assert nxt is not None
            self.assertEqual(nxt.day, 6)
            self.assertEqual(downtime.practice_time_minutes(now), 1440)

    def test_disabled(self) -> None:
        now = datetime(2026, 9, 4, 19, 0, 0, tzinfo=CT)
        with patch.dict(os.environ, {"PRACTICE_RESTART_AT": "off"}):
            self.assertIsNone(downtime.next_restart(now))
            self.assertEqual(downtime.practice_time_minutes(now), 1440)

    def test_crossed_marks_countdown(self) -> None:
        self.assertEqual(downtime.crossed_marks(None, 601), [])
        self.assertEqual(downtime.crossed_marks(601, 599), [600])
        self.assertEqual(downtime.crossed_marks(5.2, 4.8), [5])
        self.assertEqual(downtime.crossed_marks(1.1, 0.0), [1, 0])

    def test_crossed_marks_wrap_fires_zero(self) -> None:
        self.assertEqual(downtime.crossed_marks(0.3, 86399), [0])
        self.assertEqual(downtime.crossed_marks(1.2, 86399), [1, 0])

    def test_mentions_skip_manual_whitelist(self) -> None:
        whitelist = {
            "players": [
                {"steam_id": "7651", "discord_id": "111", "enabled": True},
                {"steam_id": "7652", "discord_id": "0", "enabled": True},
            ]
        }
        board = {
            "lobbies": {
                "blackhawk": {
                    "name": "Practice — Blackhawk Farms",
                    "online": [
                        {"guid": "7651", "name": "Isaac"},
                        {"guid": "7652", "name": "Guest"},
                    ],
                }
            }
        }
        self.assertEqual(downtime.mention_ids(whitelist, board), ["111"])
        lines = downtime.online_lines(whitelist, board)
        self.assertEqual(lines[0], "<@111> — Practice — Blackhawk Farms")
        self.assertEqual(lines[1], "Guest — Practice — Blackhawk Farms")

    def test_chat_and_discord_copy(self) -> None:
        self.assertIn("10 minutes", downtime.chat_text(600))
        self.assertEqual(downtime.chat_text(4), "4")
        text = downtime.discord_text(
            600,
            online=["<@111> — Blackhawk"],
            now=datetime(2026, 9, 4, 19, 0, 0, tzinfo=CT),
        )
        self.assertIn("10 minutes", text)
        self.assertIn("<@111>", text)
        self.assertIn("3:00 AM CT", downtime.discord_text(30, now=datetime(2026, 9, 4, 19, 0, tzinfo=CT)))


if __name__ == "__main__":
    unittest.main()
