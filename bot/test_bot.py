import unittest

from steam_parse import parse_profile, steam64_from_xml, vanity_slug
from players import (
    NOT_BOT_REGISTERED,
    find_livery_holder,
    is_bot_registered,
    player_for_discord,
    player_public_name,
    set_livery,
)


class ParseProfileTests(unittest.TestCase):
    def test_profiles_url(self) -> None:
        parsed = parse_profile("https://steamcommunity.com/profiles/76561197961983498/")
        assert parsed is not None
        self.assertEqual(parsed[0], "76561197961983498")
        self.assertEqual(parsed[1], "https://steamcommunity.com/profiles/76561197961983498")

    def test_bare_steam64(self) -> None:
        parsed = parse_profile("76561197961983498")
        assert parsed is not None
        self.assertEqual(parsed[0], "76561197961983498")

    def test_vanity_is_not_numeric_until_resolved(self) -> None:
        self.assertIsNone(parse_profile("https://steamcommunity.com/id/somevanity/"))
        self.assertEqual(vanity_slug("https://steamcommunity.com/id/somevanity/"), "somevanity")
        self.assertEqual(vanity_slug("https://steamcommunity.com/id/GabeNewell/?xml=1"), "GabeNewell")
        self.assertIsNone(vanity_slug("https://example.com/id/nope"))

    def test_steam64_from_xml(self) -> None:
        body = (
            '<?xml version="1.0"?>\n<profile>\n'
            "<steamID64>76561197960287930</steamID64>\n</profile>\n"
        )
        self.assertEqual(steam64_from_xml(body), "76561197960287930")
        self.assertIsNone(steam64_from_xml("<html>nope</html>"))


class BotRegistrationTests(unittest.TestCase):
    def test_manual_row_is_not_bot_registered(self) -> None:
        data = {
            "players": [
                {
                    "steam_id": "76561198014952506",
                    "discord_id": "0",
                    "enabled": True,
                }
            ]
        }
        self.assertIsNone(player_for_discord(data, "0"))
        self.assertIsNone(player_for_discord(data, "267079254141960193"))
        self.assertFalse(is_bot_registered(data["players"][0]))

    def test_approved_row_can_set_one_livery(self) -> None:
        player = {
            "steam_id": "76561198042662616",
            "discord_id": "267079254141960193",
            "enabled": True,
        }
        data = {"players": [player]}
        found = player_for_discord(data, "267079254141960193")
        self.assertIs(found, player)
        set_livery(found, "abarth_124_2016", "02_Bianco")
        self.assertEqual(found["livery"]["car"], "abarth_124_2016")
        self.assertEqual(found["livery"]["skin"], "02_Bianco")
        set_livery(found, "ks_mazda_miata", "05_sunburst_yellow")
        self.assertEqual(found["livery"]["car"], "ks_mazda_miata")
        self.assertEqual(len([k for k in found if k == "livery"]), 1)

    def test_disabled_or_missing_must_register(self) -> None:
        data = {
            "players": [
                {
                    "steam_id": "76561198042662616",
                    "discord_id": "267079254141960193",
                    "enabled": False,
                }
            ]
        }
        self.assertIsNone(player_for_discord(data, "267079254141960193"))
        self.assertIsNone(player_for_discord({"players": []}, "1"))
        self.assertIn("/steam-request", NOT_BOT_REGISTERED)


class LiveryCollisionTests(unittest.TestCase):
    def test_same_car_color_is_taken(self) -> None:
        owner = {
            "steam_id": "76561198042662616",
            "discord_id": "267079254141960193",
            "discord_name": "cysterion",
            "enabled": True,
            "livery": {"car": "abarth_124_2016", "skin": "02_Bianco"},
        }
        other = {
            "steam_id": "76561197961983498",
            "discord_id": "346358169154486273",
            "enabled": True,
        }
        data = {"players": [owner, other]}
        holder = find_livery_holder(
            data,
            "abarth_124_2016",
            "02_Bianco",
            except_steam=other["steam_id"],
            except_discord=other["discord_id"],
        )
        self.assertIs(holder, owner)
        self.assertEqual(player_public_name(owner), "<@267079254141960193>")
        self.assertIsNone(
            find_livery_holder(
                data,
                "abarth_124_2016",
                "01_Nero",
                except_steam=other["steam_id"],
            )
        )

    def test_owner_can_keep_same_pick(self) -> None:
        owner = {
            "steam_id": "76561198042662616",
            "discord_id": "267079254141960193",
            "enabled": True,
            "livery": {"car": "abarth_124_2016", "skin": "02_Bianco"},
        }
        self.assertIsNone(
            find_livery_holder(
                {"players": [owner]},
                "abarth_124_2016",
                "02_Bianco",
                except_steam=owner["steam_id"],
                except_discord=owner["discord_id"],
            )
        )


if __name__ == "__main__":
    unittest.main()
