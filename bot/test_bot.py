import asyncio
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import buildkite_trigger
from steam_parse import parse_profile, steam64_from_xml, vanity_slug
from players import (
    NOT_BOT_REGISTERED,
    find_livery_holder,
    is_bot_registered,
    player_for_discord,
    player_public_name,
    set_livery,
)
import bot


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
        # The unregistered-user copy now points at /intake, which asks for the
        # Steam URL and a race number together, rather than at /steam-request.
        # Both commands still exist in bot.py; only the guidance changed. This
        # assertion still tested the old wording because the change was made
        # directly on the box and never ran through CI.
        self.assertIn("/intake", NOT_BOT_REGISTERED)


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


class LoadLeaderboardTests(unittest.TestCase):
    def test_missing_file_returns_empty_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(bot, "LEADERBOARD_PATH", Path(raw) / "leaderboard.json"):
                self.assertEqual(bot.load_leaderboard(), {"updated": None, "lobbies": {}})

    def test_valid_file_is_read_through(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "leaderboard.json"
            path.write_text('{"updated": "now", "lobbies": {"blackhawk": {}}}', encoding="utf-8")
            with patch.object(bot, "LEADERBOARD_PATH", path):
                self.assertEqual(
                    bot.load_leaderboard(), {"updated": "now", "lobbies": {"blackhawk": {}}}
                )

    def test_corrupt_file_logs_and_degrades_instead_of_crashing(self) -> None:
        # The bot only ever reads this file -- it must never crash a
        # scheduled task or a snapshot command over a corrupt board the way
        # plugin.Leaderboard (the authoritative writer) is now allowed to.
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "leaderboard.json"
            path.write_text("{not valid json", encoding="utf-8")
            with patch.object(bot, "LEADERBOARD_PATH", path):
                with patch("sys.stderr"):
                    self.assertEqual(bot.load_leaderboard(), {"updated": None, "lobbies": {}})


class FakeStatusChannel:
    """Records what the bot would have posted to #server-status."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str, **_kwargs) -> None:
        self.sent.append(content)


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.buildkite.com/v2/access-token", code, "err", {}, io.BytesIO(body.encode("utf-8"))
    )


class BuildkiteTokenCheckTests(unittest.TestCase):
    # Night of 12 Sep 2026 the token in /var/lib/ac-host/.env was dead and
    # nobody learned it until the 03:00 trigger got its 401 in docker logs.
    # check_token asks Buildkite at startup instead. No network: the opener
    # is injected.

    def test_live_token_reports_scopes(self) -> None:
        seen: dict = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self):
                return b'{"uuid": "u", "scopes": ["read_builds", "write_builds"]}'

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            return Response()

        ok, detail = buildkite_trigger.check_token(token="bkua_secret", opener=opener)
        self.assertTrue(ok)
        self.assertEqual(seen["url"], "https://api.buildkite.com/v2/access-token")
        self.assertEqual(seen["auth"], "Bearer bkua_secret")
        self.assertIn("write_builds", detail)
        self.assertNotIn("bkua_secret", detail)

    def test_401_is_a_verdict_not_an_exception(self) -> None:
        def opener(request, timeout):
            raise _http_error(401, '{"message": "Authorization failed"}')

        ok, detail = buildkite_trigger.check_token(token="bkua_dead", opener=opener)
        self.assertFalse(ok)
        self.assertIn("HTTP 401", detail)
        self.assertIn("Authorization failed", detail)
        self.assertNotIn("bkua_dead", detail)

    def test_network_failure_is_a_verdict_not_an_exception(self) -> None:
        def opener(request, timeout):
            raise urllib.error.URLError("no route to host")

        ok, detail = buildkite_trigger.check_token(token="bkua_x", opener=opener)
        self.assertFalse(ok)
        self.assertIn("no route to host", detail)

    def test_missing_token_is_bad(self) -> None:
        ok, detail = buildkite_trigger.check_token(token="", opener=lambda *a, **k: self.fail("no request"))
        self.assertFalse(ok)
        self.assertIn("BUILDKITE_API_TOKEN", detail)


class StartupTokenVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        bot.bot._buildkite_token_posted = False

    def _run(self, stub) -> FakeStatusChannel:
        channel = FakeStatusChannel()

        async def status_channel():
            return channel

        with patch.object(bot, "buildkite_trigger", stub), patch.object(
            bot, "status_text_channel", status_channel
        ), patch("builtins.print"):
            asyncio.run(bot.report_buildkite_token())
        return channel

    def test_bad_token_is_posted_once_naming_the_fix(self) -> None:
        stub = SimpleNamespace(
            configured=lambda: True,
            check_token=lambda: (False, "GET /v2/access-token HTTP 401: Authorization failed"),
        )
        channel = self._run(stub)
        self.assertEqual(len(channel.sent), 1)
        self.assertIn("FAILED", channel.sent[0])
        self.assertIn("HTTP 401", channel.sent[0])
        self.assertIn("BUILDKITE_API_TOKEN in /var/lib/ac-host/.env", channel.sent[0])
        self.assertIn("ac-host-bot.service", channel.sent[0])
        # on_ready fires again on every reconnect; the token does not change
        # until the process restarts, so the channel hears it once.
        again = self._run(stub)
        self.assertEqual(again.sent, [])

    def test_good_token_posts_nothing(self) -> None:
        stub = SimpleNamespace(configured=lambda: True, check_token=lambda: (True, "scopes write_builds"))
        self.assertEqual(self._run(stub).sent, [])

    def test_unconfigured_buildkite_posts_nothing(self) -> None:
        stub = SimpleNamespace(configured=lambda: False, check_token=lambda: self.fail("no check"))
        self.assertEqual(self._run(stub).sent, [])


class DowntimeTriggerFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        bot.bot._drill_at = None
        bot.bot._downtime_pipeline_date = None

    def _stub(self, trigger):
        return SimpleNamespace(
            configured=lambda: True,
            pipeline_slug=lambda kind="ci": "ac-host-ops" if kind == "ops" else "ac-host",
            trigger_downtime=trigger,
        )

    def test_trigger_exception_becomes_operator_text(self) -> None:
        def trigger():
            raise RuntimeError('Buildkite trigger failed HTTP 401: {"message":"Authorization failed"}')

        with patch.object(bot, "buildkite_trigger", self._stub(trigger)), patch("builtins.print"):
            text = bot._queue_downtime_pipeline()
        assert text is not None
        self.assertIn("NOT queued", text)
        self.assertIn("HTTP 401", text)
        self.assertIn("pipeline ac-host-ops", text)
        self.assertIn("rotate BUILDKITE_API_TOKEN in /var/lib/ac-host/.env", text)
        # Not marked queued: the build did not happen.
        self.assertIsNone(bot.bot._downtime_pipeline_date)

    def test_non_auth_failure_points_at_the_logs_first(self) -> None:
        def trigger():
            raise RuntimeError("Buildkite trigger failed HTTP 503: upstream")

        with patch.object(bot, "buildkite_trigger", self._stub(trigger)), patch("builtins.print"):
            text = bot._queue_downtime_pipeline()
        assert text is not None
        self.assertIn("HTTP 503", text)
        self.assertIn("journalctl -u ac-host-bot.service", text)

    def test_queued_build_returns_nothing_to_post(self) -> None:
        stub = self._stub(lambda: {"web_url": "https://buildkite.com/b/1"})
        with patch.object(bot, "buildkite_trigger", stub), patch("builtins.print"):
            self.assertIsNone(bot._queue_downtime_pipeline())
        self.assertIsNotNone(bot.bot._downtime_pipeline_date)

    def test_mark_zero_posts_the_failure_to_status_channel(self) -> None:
        channel = FakeStatusChannel()

        async def status_channel():
            return channel

        failure = bot.downtime_failure_text("Buildkite trigger failed HTTP 401: nope", "ac-host-ops")
        with patch.object(bot, "status_text_channel", status_channel), patch.object(
            bot, "_queue_downtime_pipeline", lambda: failure
        ), patch.object(bot, "load_whitelist", lambda: {"players": []}), patch.object(
            bot, "load_leaderboard", lambda: {"updated": None, "lobbies": {}}
        ), patch("builtins.print"):
            asyncio.run(bot.fire_downtime_mark(0))
        self.assertEqual(channel.sent[0], failure)
        # The mark-0 countdown line still goes out after it.
        self.assertEqual(len(channel.sent), 2)

    def test_drill_at_mark_zero_never_posts_a_failure(self) -> None:
        channel = FakeStatusChannel()

        async def status_channel():
            return channel

        bot.bot._drill_at = bot.downtime.now_local()
        try:
            with patch.object(bot, "status_text_channel", status_channel), patch.object(
                bot, "_queue_downtime_pipeline", lambda: self.fail("drill must not trigger")
            ), patch.object(bot, "load_whitelist", lambda: {"players": []}), patch.object(
                bot, "load_leaderboard", lambda: {"updated": None, "lobbies": {}}
            ), patch("builtins.print"):
                asyncio.run(bot.fire_downtime_mark(0))
        finally:
            bot.bot._drill_at = None
        self.assertEqual(len(channel.sent), 1)
        self.assertNotIn("NOT queued", channel.sent[0])


if __name__ == "__main__":
    unittest.main()
