#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import udr_fw_exporter as exp


class UdrFwExporterTests(unittest.TestCase):
    def test_render_metrics_filters_lan_and_escapes(self) -> None:
        text = exp.render_metrics(
            [
                {"chain": "LAN_IN", "id": "1", "packets": 9},
                {"chain": "WAN_PF_IN", "id": '12"3', "packets": 12},
                {"chain": "WAN_LOCAL", "id": "30001", "packets": 3},
            ]
        )
        self.assertIn(
            'udr_firewall_packets_total{chain="WAN_PF_IN",rule="12\\"3"} 12',
            text,
        )
        self.assertIn(
            'udr_firewall_packets_total{chain="WAN_LOCAL",rule="30001"} 3',
            text,
        )
        self.assertNotIn("LAN_IN", text)


if __name__ == "__main__":
    unittest.main()
