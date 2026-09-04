import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_discord as setup


class PermanentInviteTests(unittest.TestCase):
    def test_picks_never_expire_unlimited(self) -> None:
        url = setup.pick_permanent_invite(
            [
                {"code": "temp", "max_age": 86400, "max_uses": 0},
                {"code": "once", "max_age": 0, "max_uses": 1},
                {"code": "keep", "max_age": 0, "max_uses": 0, "temporary": False},
            ]
        )
        self.assertEqual(url, "https://discord.gg/keep")

    def test_skips_temporary_membership(self) -> None:
        self.assertIsNone(
            setup.pick_permanent_invite(
                [{"code": "tmp", "max_age": 0, "max_uses": 0, "temporary": True}]
            )
        )

    def test_empty_list(self) -> None:
        self.assertIsNone(setup.pick_permanent_invite([]))


if __name__ == "__main__":
    unittest.main()
