import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plugin


def pack_connection(name: str, guid: str, car_id: int, car: str, skin: str) -> bytes:
    return (
        plugin.write_utf(name)
        + plugin.write_utf(guid)
        + bytes([car_id])
        + plugin.write_ascii(car)
        + plugin.write_ascii(skin)
    )


class ProtocolTests(unittest.TestCase):
    def test_utf_roundtrip(self) -> None:
        raw = plugin.write_utf("Isaac")
        self.assertEqual(plugin.Reader(raw).utf(), "Isaac")

    def test_new_connection(self) -> None:
        payload = pack_connection("Isaac", "76561198000000001", 3, "abarth_124_2016", "02_Bianco")
        info = plugin.parse_new_connection(payload)
        self.assertEqual(info["name"], "Isaac")
        self.assertEqual(info["guid"], "76561198000000001")
        self.assertEqual(info["car_id"], 3)
        self.assertEqual(info["car"], "abarth_124_2016")

    def test_lap_completed_ignores_tail(self) -> None:
        payload = bytes([4]) + struct.pack("<I", 91234) + bytes([0, 2, 0, 0, 0, 0])
        car_id, laptime, cuts = plugin.parse_lap_completed(payload)
        self.assertEqual(car_id, 4)
        self.assertEqual(laptime, 91234)
        self.assertEqual(cuts, 0)

    def test_car_info(self) -> None:
        payload = (
            bytes([1, 1])
            + plugin.write_utf("abarth_124_2016")
            + plugin.write_utf("02_Bianco")
            + plugin.write_utf("Isaac")
            + plugin.write_utf("")
            + plugin.write_utf("76561198000000001")
        )
        info = plugin.parse_car_info(payload)
        self.assertTrue(info["connected"])
        self.assertEqual(info["guid"], "76561198000000001")
        self.assertEqual(info["name"], "Isaac")
        self.assertEqual(info["car"], "abarth_124_2016")


class BoardTests(unittest.TestCase):
    def test_cuts_and_short_laps_rejected(self) -> None:
        self.assertFalse(plugin.valid_lap(91234, 1, "76561198000000001"))
        self.assertFalse(plugin.valid_lap(1000, 0, "76561198000000001"))
        self.assertFalse(plugin.valid_lap(91234, 0, ""))
        self.assertTrue(plugin.valid_lap(91234, 0, "76561198000000001"))

    def test_upsert_keeps_faster_time_and_latest_name(self) -> None:
        entries: list[dict] = []
        plugin.upsert_entry(
            entries,
            {"guid": "1", "name": "Old", "car": "abarth_124_2016", "ms": 100000, "at": "a", "carName": "124"},
        )
        slower = plugin.upsert_entry(
            entries,
            {"guid": "1", "name": "New", "car": "abarth_124_2016", "ms": 110000, "at": "b", "carName": "124"},
        )
        faster = plugin.upsert_entry(
            entries,
            {"guid": "1", "name": "New", "car": "abarth_124_2016", "ms": 90000, "at": "c", "carName": "124"},
        )
        self.assertFalse(slower)
        self.assertTrue(faster)
        self.assertEqual(entries[0]["ms"], 90000)
        self.assertEqual(entries[0]["name"], "New")
        other = plugin.upsert_entry(
            entries,
            {"guid": "1", "name": "New", "car": "tbb_toyota_gr86_premium", "ms": 95000, "at": "d", "carName": "GR86"},
        )
        self.assertTrue(other)
        self.assertEqual(len(entries), 2)

    def test_save_schedules_push(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            statics = [{"id": "blackhawk", "name": "Practice — Blackhawk Farms", "track": "blackhawk", "slot": 0}]
            with patch("push_status.schedule_push") as mock_push:
                board = plugin.Leaderboard(
                    path=root / "leaderboard.json",
                    dist=root / "dist" / "leaderboard.json",
                    statics=statics,
                    car_names={"abarth_124_2016": "Abarth 124 Spider EC P1"},
                )
                board.record(
                    "blackhawk",
                    guid="76561198000000001",
                    name="Isaac",
                    car="abarth_124_2016",
                    ms=91234,
                    cuts=0,
                )
                self.assertTrue(mock_push.called)
                pushed = mock_push.call_args[0][0]
                self.assertIn("76561198000000001", pushed)

    def test_leaderboard_persists_and_session_reset(self) -> None:
        with patch("push_status.schedule_push"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                statics = [{"id": "blackhawk", "name": "Practice — Blackhawk Farms", "track": "blackhawk", "slot": 0}]
                board = plugin.Leaderboard(
                    path=root / "leaderboard.json",
                    dist=root / "dist" / "leaderboard.json",
                    statics=statics,
                    car_names={"abarth_124_2016": "Abarth 124 Spider EC P1"},
                )
                board.record(
                    "blackhawk",
                    guid="76561198000000001",
                    name="Isaac",
                    car="abarth_124_2016",
                    ms=91234,
                    cuts=0,
                )
                data = json.loads((root / "dist" / "leaderboard.json").read_text(encoding="utf-8"))
                row = data["lobbies"]["blackhawk"]["allTime"][0]
                self.assertEqual(row["guid"], "76561198000000001")
                self.assertEqual(row["name"], "Isaac")
                self.assertEqual(row["carName"], "Abarth 124 Spider EC P1")
                self.assertEqual(len(data["lobbies"]["blackhawk"]["session"]), 1)
                board.reset_session("blackhawk")
                data = json.loads((root / "leaderboard.json").read_text(encoding="utf-8"))
                self.assertEqual(data["lobbies"]["blackhawk"]["session"], [])
                self.assertEqual(len(data["lobbies"]["blackhawk"]["allTime"]), 1)

    def test_slot_mapping(self) -> None:
        statics = [{"id": "blackhawk", "slot": 0}, {"id": "brainerd-competition", "slot": 1}]
        self.assertEqual(plugin.slot_to_lobby_id(0, statics, {}), "blackhawk")
        self.assertEqual(plugin.slot_to_lobby_id(1, statics, {}), "brainerd-competition")
        self.assertEqual(plugin.slot_to_lobby_id(3, statics, {"sprint1": {"slot": 3}}), "race-sprint1")

    def test_plugin_handle_join_and_lap(self) -> None:
        with patch("push_status.schedule_push"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                catalog = root / "catalog"
                (catalog / "cars").mkdir(parents=True)
                (catalog / "cars" / "abarth_124_2016.json").write_text(
                    '{"folder":"abarth_124_2016","displayName":"Abarth 124 Spider EC P1"}\n',
                    encoding="utf-8",
                )
                (catalog / "statics.json").write_text(
                    json.dumps(
                        {
                            "lobbies": [
                                {
                                    "id": "blackhawk",
                                    "name": "Practice — Blackhawk Farms",
                                    "track": "blackhawk",
                                    "slot": 0,
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                sidecar = plugin.Plugin(state=root, catalog=catalog, dist=root / "dist", slots=[0])
                sidecar.handle(
                    0,
                    bytes([plugin.ACSP_NEW_CONNECTION])
                    + pack_connection("Isaac", "76561198000000001", 3, "abarth_124_2016", "02_Bianco"),
                )
                sidecar.handle(0, bytes([plugin.ACSP_LAP_COMPLETED, 3]) + struct.pack("<I", 12000) + bytes([0]))
                sidecar.handle(0, bytes([plugin.ACSP_LAP_COMPLETED, 3]) + struct.pack("<I", 91234) + bytes([1]))
                sidecar.handle(0, bytes([plugin.ACSP_LAP_COMPLETED, 3]) + struct.pack("<I", 91234) + bytes([0]))
                data = json.loads((root / "dist" / "leaderboard.json").read_text(encoding="utf-8"))
                rows = data["lobbies"]["blackhawk"]["allTime"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["guid"], "76561198000000001")
                self.assertEqual(rows[0]["name"], "Isaac")
                self.assertEqual(rows[0]["ms"], 91234)
                self.assertEqual(data["lobbies"]["blackhawk"]["online"][0]["name"], "Isaac")
                sidecar.handle(
                    0,
                    bytes([plugin.ACSP_CONNECTION_CLOSED])
                    + pack_connection("Isaac", "76561198000000001", 3, "abarth_124_2016", "02_Bianco"),
                )
                data = json.loads((root / "dist" / "leaderboard.json").read_text(encoding="utf-8"))
                self.assertEqual(data["lobbies"]["blackhawk"]["online"], [])

    def test_plugin_clears_stale_online_on_start(self) -> None:
        with patch("push_status.schedule_push"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                catalog = root / "catalog"
                (catalog / "cars").mkdir(parents=True)
                (catalog / "statics.json").write_text(
                    json.dumps(
                        {
                            "lobbies": [
                                {
                                    "id": "blackhawk",
                                    "name": "Practice — Blackhawk Farms",
                                    "track": "blackhawk",
                                    "slot": 0,
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                (root / "leaderboard.json").write_text(
                    json.dumps(
                        {
                            "updated": "2026-01-01T00:00:00+00:00",
                            "lobbies": {
                                "blackhawk": {
                                    "id": "blackhawk",
                                    "name": "Practice — Blackhawk Farms",
                                    "track": "blackhawk",
                                    "online": [
                                        {
                                            "guid": "76561198000000001",
                                            "name": "Ghost",
                                            "car": "abarth_124_2016",
                                            "carName": "124",
                                        }
                                    ],
                                    "allTime": [],
                                    "session": [],
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                plugin.Plugin(state=root, catalog=catalog, dist=root / "dist", slots=[])
                data = json.loads((root / "dist" / "leaderboard.json").read_text(encoding="utf-8"))
                self.assertEqual(data["lobbies"]["blackhawk"]["online"], [])


    def test_resolve_plugin_slots_from_catalog_and_races(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            catalog = root / "catalog"
            catalog.mkdir()
            (catalog / "statics.json").write_text(
                json.dumps({"lobbies": [{"id": "blackhawk", "slot": 0}]}),
                encoding="utf-8",
            )
            (root / "slots.json").write_text(
                json.dumps({"sprint1": {"slot": 3}}),
                encoding="utf-8",
            )
            slots = plugin.resolve_plugin_slots(root, catalog)
            self.assertEqual(slots, [0, 3])

    def test_resolve_plugin_slots_override(self) -> None:
        with patch.dict("os.environ", {"PLUGIN_SLOTS": "8,9"}):
            slots = plugin.resolve_plugin_slots(Path("/tmp"), Path("/tmp"))
            self.assertEqual(slots, [8, 9])

    def test_slot_from_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            cfg = Path(raw) / "cfg"
            cfg.mkdir()
            (cfg / "server_cfg.ini").write_text(
                "[SERVER]\nUDP_PORT=9608\nHTTP_PORT=8089\n",
                encoding="utf-8",
            )
            self.assertEqual(plugin.slot_from_cfg(cfg), 8)


if __name__ == "__main__":
    unittest.main()
