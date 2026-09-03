#!/usr/bin/env python3
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unifi_pf


class UnifiPfTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(unifi_pf.enabled())

    def test_rule_names(self) -> None:
        names = unifi_pf.rule_names("prod", 3)
        self.assertEqual(names["game"], "ac-prod-s3-game")
        self.assertEqual(names["http"], "ac-prod-s3-http")
        self.assertEqual(names["details"], "ac-prod-s3-details")

    def test_open_slot_noop_when_disabled(self) -> None:
        with patch.dict("os.environ", {"UNIFI_PF": "0"}, clear=False):
            unifi_pf.open_slot("prod", 3, 9603, 8084, 8184)

    def test_ensure_rule_creates_when_missing(self) -> None:
        client = unifi_pf.UnifiPortForward()
        client.fwd = "192.168.1.50"
        client.iface = "wan"
        client._opener = MagicMock()
        client._csrf = "tok"
        with patch.object(client, "list_rules", return_value=[]):
            with patch.object(client, "_request") as req:
                client.ensure_rule(name="ac-prod-s3-game", proto="tcp_udp", port=9603)
                req.assert_called_once()
                method, path, body = req.call_args[0]
                self.assertEqual(method, "POST")
                self.assertEqual(path, "rest/portforward")
                self.assertEqual(body["dst_port"], "9603")
                self.assertEqual(body["fwd"], "192.168.1.50")
                self.assertEqual(body["proto"], "tcp_udp")

    def test_ensure_rule_skips_identical(self) -> None:
        client = unifi_pf.UnifiPortForward()
        client.fwd = "192.168.1.50"
        client.iface = "wan"
        existing = [
            {
                "_id": "abc",
                "name": "ac-prod-s3-game",
                "enabled": True,
                "dst_port": "9603",
                "fwd": "192.168.1.50",
                "fwd_port": "9603",
                "proto": "tcp_udp",
            }
        ]
        with patch.object(client, "list_rules", return_value=existing):
            with patch.object(client, "_request") as req:
                client.ensure_rule(name="ac-prod-s3-game", proto="tcp_udp", port=9603)
                req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
