import unittest

from auth import decide, extract_guid, format_reply


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.whitelist = {
            "players": [
                {
                    "steam_id": "76561198000000001",
                    "roles": ["ac-practice"],
                    "enabled": True,
                },
                {
                    "steam_id": "76561198000000002",
                    "roles": ["ac-practice"],
                    "enabled": False,
                },
                {
                    "steam_id": "76561198000000003",
                    "roles": ["ac-race"],
                    "enabled": True,
                },
            ]
        }

    def test_open_mode_allows_anything(self) -> None:
        allowed, reason = decide("", self.whitelist, open_mode=True, required_role="ac-practice")
        self.assertTrue(allowed)
        self.assertEqual(reason, "open")

    def test_member_with_role(self) -> None:
        allowed, _ = decide(
            "76561198000000001",
            self.whitelist,
            open_mode=False,
            required_role="ac-practice",
        )
        self.assertTrue(allowed)

    def test_disabled(self) -> None:
        allowed, reason = decide(
            "76561198000000002",
            self.whitelist,
            open_mode=False,
            required_role="ac-practice",
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "disabled")

    def test_wrong_role(self) -> None:
        allowed, reason = decide(
            "76561198000000003",
            self.whitelist,
            open_mode=False,
            required_role="ac-practice",
        )
        self.assertFalse(allowed)
        self.assertIn("missing role", reason)

    def test_unknown(self) -> None:
        allowed, reason = decide(
            "76561198000000999",
            self.whitelist,
            open_mode=False,
            required_role="ac-practice",
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "not on the list")

    def test_guid_keys(self) -> None:
        self.assertEqual(extract_guid({"GUID": ["76561198000000001"]}), "76561198000000001")

    def test_reply_format(self) -> None:
        self.assertEqual(format_reply(True, "ok"), b"0:ok\n")
        self.assertEqual(format_reply(False, "no"), b"1:no\n")


if __name__ == "__main__":
    unittest.main()
