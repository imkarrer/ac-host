import json
import tempfile
import unittest
from pathlib import Path

import server_health


class ServerHealthTests(unittest.TestCase):
    def test_apply_sets_maintenance_from_flag(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            server_health.write_flag(state, "Box is open, wiring is not.")
            payload = server_health.apply_to_payload({"lobbies": {}}, state)
            self.assertEqual(payload["status"], "maintenance")
            self.assertEqual(payload["statusMessage"], "Box is open, wiring is not.")
            self.assertTrue(server_health.is_down(payload))

    def test_apply_clears_status_when_flag_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            server_health.write_flag(state, "soon")
            payload = {"status": "maintenance", "statusMessage": "soon", "lobbies": {}}
            server_health.clear_flag(state)
            server_health.apply_to_payload(payload, state)
            self.assertEqual(payload["status"], "up")
            self.assertNotIn("statusMessage", payload)
            self.assertFalse(server_health.is_down(payload))

    def test_missing_flag_file_is_up(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            payload = server_health.apply_to_payload({}, Path(raw))
            self.assertEqual(payload["status"], "up")

    def test_write_flag_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            path = server_health.write_flag(state)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["message"], server_health.DEFAULT_MESSAGE)


if __name__ == "__main__":
    unittest.main()
