import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_manifest import CAR, DOWNLOADABLE_CARS, PRACTICE_TRACKS, content_payload


class ContentManifestTests(unittest.TestCase):
    def test_payload_keeps_hosted_cars_and_practice_tracks(self) -> None:
        payload = content_payload("imkarrer", "ac-practice", car_version="2.2")
        self.assertEqual(payload["cars"][CAR]["version"], "2.2")
        self.assertIn("abarth_124_2016.zip", payload["cars"][CAR]["url"])
        hosted = {item["id"] for item in DOWNLOADABLE_CARS}
        self.assertEqual(set(payload["cars"]), hosted)
        self.assertEqual(payload["cars"]["tbb_toyota_gr86_premium"]["version"], "2.0.1")
        self.assertEqual(payload["cars"]["pc_civic"]["version"], "1.02")
        self.assertEqual(payload["cars"]["some1_honda_nsx_1997_s1"]["version"], "3.0.0")
        self.assertIn("tbb_toyota_gr86_premium.zip", payload["cars"]["tbb_toyota_gr86_premium"]["url"])
        self.assertIn("pc_civic.zip", payload["cars"]["pc_civic"]["url"])
        self.assertIn("some1_honda_nsx_1997_s1.zip", payload["cars"]["some1_honda_nsx_1997_s1"]["url"])
        self.assertNotIn("some1_honda_nsx_r_1994", payload["cars"])
        self.assertNotIn("ks_mazda_miata", payload["cars"])
        folders = {item["folder"] for item in PRACTICE_TRACKS}
        self.assertEqual(set(payload["tracks"]), folders)
        self.assertNotIn("autobahn_cc", payload["tracks"])
        self.assertEqual(
            payload["tracks"]["lilski_road_america"]["url"],
            "https://github.com/imkarrer/ac-practice/releases/download/content/lilski_road_america.zip",
        )


if __name__ == "__main__":
    unittest.main()
