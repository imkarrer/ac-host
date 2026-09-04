import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import details


class DetailsTests(unittest.TestCase):
    def test_fill_empty_skins_uses_preferred(self):
        with tempfile.TemporaryDirectory() as raw:
            content = Path(raw)
            bianco = content / "cars" / "abarth_124_2016" / "skins" / "02_Bianco"
            rosso = content / "cars" / "abarth_124_2016" / "skins" / "00_Rosso"
            bianco.mkdir(parents=True)
            rosso.mkdir(parents=True)
            (bianco / "preview.jpg").write_bytes(b"x")
            (rosso / "preview.jpg").write_bytes(b"x")
            slots = [
                {"Model": "abarth_124_2016", "Skin": "", "IsConnected": False},
                {"Model": "abarth_124_2016", "Skin": "", "IsConnected": True},
            ]
            filled = details.fill_empty_skins(slots, content)
            self.assertEqual(filled[0]["Skin"], "02_Bianco")
            self.assertEqual(filled[1]["Skin"], "")

    def test_payload_advertises_practice_and_pickup(self):
        with tempfile.TemporaryDirectory() as raw:
            cfg = Path(raw) / "cfg"
            cfg.mkdir()
            (cfg / "server_cfg.ini").write_text(
                "[SERVER]\nNAME=Test\nCARS=abarth_124_2016\n"
                "UDP_PORT=9600\nTCP_PORT=9600\nHTTP_PORT=8081\nMAX_CLIENTS=2\n"
                "TRACK=slipangle_ggt\n",
                encoding="utf-8",
            )
            (cfg / "entry_list.ini").write_text(
                "[CAR_0]\nMODEL=abarth_124_2016\nSKIN=\nDRIVERNAME=\nTEAM=\n",
                encoding="utf-8",
            )
            content = Path(raw) / "content"
            skin = content / "cars" / "abarth_124_2016" / "skins" / "02_Bianco"
            skin.mkdir(parents=True)
            (skin / "preview.jpg").write_bytes(b"x")
            with patch.object(details, "load_info", return_value={"timeleft": 100, "clients": 0}):
                with patch.object(details, "load_players", return_value=[]):
                    payload = details.details_payload(cfg, content, 8181, "76561197961983498")
            self.assertEqual(payload["session"], 1)
            self.assertEqual(payload["sessiontypes"], [1])
            self.assertTrue(payload["pickup"])
            cars = payload["players"]["Cars"]
            self.assertEqual(cars[0]["Skin"], "02_Bianco")
            self.assertTrue(cars[0]["IsEntryList"])

    def test_cm_content_124_only(self):
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            dist = state / "dist"
            dist.mkdir()
            release = "https://github.com/me/ac-practice/releases/download/content/abarth_124_2016.zip"
            (dist / "content.json").write_text(
                json.dumps(
                    {
                        "cars": {
                            "abarth_124_2016": {
                                "url": release,
                                "version": "1.3",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            shaped = details.load_cm_content("slipangle_ggt", state=state)
            self.assertEqual(shaped["cars"]["abarth_124_2016"]["url"], release)
            self.assertNotIn("track", shaped)
            self.assertNotIn("tracks", shaped)

    def test_cm_content_emits_singular_track_when_configured(self):
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            dist = state / "dist"
            dist.mkdir()
            (dist / "content.json").write_text(
                json.dumps(
                    {
                        "cars": {
                            "abarth_124_2016": {
                                "url": "http://192.168.1.50:8099/abarth_124_2016.zip",
                                "version": "1.1",
                            }
                        },
                        "tracks": {
                            "slipangle_ggt": {
                                "url": "http://192.168.1.50:8099/slipangle_ggt.zip",
                                "version": "1.1.1",
                            },
                            "gb_brainerd": {
                                "url": "http://192.168.1.50:8099/gb_brainerd.zip",
                                "version": "1.1",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            blackhawk = details.load_cm_content("slipangle_ggt", state=state)
            self.assertEqual(
                blackhawk["track"]["url"],
                "http://192.168.1.50:8099/slipangle_ggt.zip",
            )
            self.assertNotIn("tracks", blackhawk)
            self.assertIn("abarth_124_2016", blackhawk["cars"])
            brainerd = details.load_cm_content("gb_brainerd", state=state)
            self.assertEqual(
                brainerd["track"]["url"],
                "http://192.168.1.50:8099/gb_brainerd.zip",
            )
            empty = details.load_cm_content("magione", state=state)
            self.assertNotIn("track", empty)

    def test_payload_advertises_this_lobby_track(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cfg = root / "cfg"
            cfg.mkdir()
            (cfg / "server_cfg.ini").write_text(
                "[SERVER]\nNAME=Test\nCARS=abarth_124_2016\n"
                "UDP_PORT=9600\nTCP_PORT=9600\nHTTP_PORT=8081\nMAX_CLIENTS=2\n"
                "TRACK=gb_brainerd\n",
                encoding="utf-8",
            )
            (cfg / "entry_list.ini").write_text(
                "[CAR_0]\nMODEL=abarth_124_2016\nSKIN=\nDRIVERNAME=\nTEAM=\n",
                encoding="utf-8",
            )
            content = root / "content"
            skin = content / "cars" / "abarth_124_2016" / "skins" / "02_Bianco"
            skin.mkdir(parents=True)
            (skin / "preview.jpg").write_bytes(b"x")
            dist = root / "dist"
            dist.mkdir()
            (dist / "content.json").write_text(
                json.dumps(
                    {
                        "cars": {"abarth_124_2016": {"url": "http://x/c.zip"}},
                        "tracks": {
                            "slipangle_ggt": {"url": "http://x/g.zip"},
                            "gb_brainerd": {"url": "http://x/b.zip"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(details, "load_info", return_value={"timeleft": 100, "clients": 0}):
                with patch.object(details, "load_players", return_value=[]):
                    with patch.dict("os.environ", {"AC_STATE": str(root)}):
                        payload = details.details_payload(cfg, content, 8181)
            self.assertEqual(payload["content"]["track"]["url"], "http://x/b.zip")
            self.assertNotIn("tracks", payload["content"])

    def test_json_roundtrip_session_type(self):
        raw = json.dumps({"session": 1, "sessiontypes": [1], "pickup": True})
        data = json.loads(raw)
        self.assertEqual(data["session"], 1)
        self.assertEqual(data["sessiontypes"][0], 1)

    def test_log_skips_ok_and_not_found(self):
        handler = details.DetailsHandler.__new__(details.DetailsHandler)
        handler.address_string = lambda: "1.2.3.4"
        with patch("builtins.print") as mock_print:
            handler.log_message('"%s" %s %s', "GET /api/details HTTP/1.1", "200", "-")
            handler.log_message('"%s" %s %s', "GET /favicon.ico HTTP/1.1", "404", "-")
            handler.log_message('"%s" %s %s', "HEAD / HTTP/1.1", "501", "-")
        printed = [call.args[0] for call in mock_print.call_args_list]
        self.assertEqual(len(printed), 1)
        self.assertIn("501", printed[0])


if __name__ == "__main__":
    unittest.main()
