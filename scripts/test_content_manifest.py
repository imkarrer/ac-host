import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_manifest import CAR, PRACTICE_TRACKS, content_payload


class ContentManifestTests(unittest.TestCase):
    def test_payload_keeps_124_and_practice_tracks(self) -> None:
        payload = content_payload("imkarrer", "ac-practice", car_version="2.2")
        self.assertEqual(payload["cars"][CAR]["version"], "2.2")
        self.assertIn("abarth_124_2016.zip", payload["cars"][CAR]["url"])
        folders = {item["folder"] for item in PRACTICE_TRACKS}
        self.assertEqual(set(payload["tracks"]), folders)
        self.assertNotIn("autobahn_cc", payload["tracks"])
        self.assertEqual(
            payload["tracks"]["lilski_road_america"]["url"],
            "https://github.com/imkarrer/ac-practice/releases/download/content/lilski_road_america.zip",
        )


if __name__ == "__main__":
    unittest.main()
