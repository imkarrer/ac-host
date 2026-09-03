import sys
import unittest
from pathlib import Path

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
        )
        self.assertIn("UDP_PLUGIN_LOCAL_PORT=11200", text)
        self.assertIn("UDP_PLUGIN_ADDRESS=127.0.0.1:11300", text)


if __name__ == "__main__":
    unittest.main()
