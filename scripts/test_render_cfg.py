import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_cfg import plugin_ports, server_cfg


class RenderCfgPluginTests(unittest.TestCase):
    def test_plugin_ports_follow_udp_slot(self) -> None:
        self.assertEqual(plugin_ports(9600), (11200, 11300))
        self.assertEqual(plugin_ports(9602), (11202, 11302))

    def test_server_cfg_points_plugin_at_localhost(self) -> None:
        text = server_cfg(
            name="Practice — Blackhawk Farms",
            track={"folder": "slipangle_ggt", "layout": "", "cars": ["abarth_124_2016"], "maxClients": 24},
            mode="practice",
            udp=9600,
            tcp=9600,
            http=8081,
            auth="127.0.0.1:18080",
            admin_password="x",
            loop=1,
            register=0,
        )
        self.assertIn("UDP_PLUGIN_LOCAL_PORT=11200", text)
        self.assertIn("UDP_PLUGIN_ADDRESS=127.0.0.1:11300", text)
        self.assertIn("TYRE_BLANKETS_ALLOWED=1", text)
        self.assertIn("REGISTER_TO_LOBBY=0", text)

    def test_register_to_lobby_env(self) -> None:
        from render_cfg import register_to_lobby, server_cfg

        with patch.dict("os.environ", {"REGISTER_TO_LOBBY": "1"}):
            self.assertEqual(register_to_lobby(), 1)
            text = server_cfg(
                name="Practice — Blackhawk Farms",
                track={"folder": "slipangle_ggt", "layout": "", "cars": ["abarth_124_2016"], "maxClients": 24},
                mode="practice",
                udp=9600,
                tcp=9600,
                http=8081,
                auth="127.0.0.1:18080",
                admin_password="x",
                loop=1,
            )
            self.assertIn("REGISTER_TO_LOBBY=1", text)
        with patch.dict("os.environ", {"REGISTER_TO_LOBBY": "0"}):
            self.assertEqual(register_to_lobby(), 0)


class PracticeTimeTests(unittest.TestCase):
    def test_practice_time_is_minutes_until_3am(self) -> None:
        with patch("render_cfg.downtime.practice_time_minutes", return_value=480):
            text = server_cfg(
                name="Practice — Blackhawk Farms",
                track={"folder": "slipangle_ggt", "layout": "", "cars": ["abarth_124_2016"], "maxClients": 24},
                mode="practice",
                udp=9600,
                tcp=9600,
                http=8081,
                auth="127.0.0.1:18080",
                admin_password="x",
                loop=1,
                register=0,
            )
        self.assertIn("TIME=480", text)
        self.assertNotIn("TIME=1440", text)

    def test_race_practice_time_stays_ten(self) -> None:
        text = server_cfg(
            name="Race",
            track={"folder": "slipangle_ggt", "layout": "", "cars": ["abarth_124_2016"], "maxClients": 24},
            mode="race",
            udp=9600,
            tcp=9600,
            http=8081,
            auth="127.0.0.1:18080",
            admin_password="x",
            loop=0,
            register=0,
        )
        self.assertIn("TIME=10", text)


if __name__ == "__main__":
    unittest.main()
