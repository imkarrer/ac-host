import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_content import (
    assert_zip_data_matches_source,
    car_requires_csp,
    content_manager_asset_url,
    pack_folder,
    should_skip,
)


class PackContentTests(unittest.TestCase):
    def test_zip_root_is_folder_id(self):
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "gb_brainerd"
            (src / "ui" / "competition").mkdir(parents=True)
            (src / "ui" / "donnybrooke").mkdir(parents=True)
            (src / "ui" / "competition" / "ui_track.json").write_text("{}", encoding="utf-8")
            (src / "ui" / "donnybrooke" / "ui_track.json").write_text("{}", encoding="utf-8")
            (src / "models.kn5").write_bytes(b"kn5")
            dest = Path(raw) / "gb_brainerd.zip"
            pack_folder(src, dest)
            with zipfile.ZipFile(dest) as zf:
                names = zf.namelist()
            self.assertIn("gb_brainerd/ui/competition/ui_track.json", names)
            self.assertIn("gb_brainerd/ui/donnybrooke/ui_track.json", names)
            self.assertIn("gb_brainerd/models.kn5", names)
            self.assertTrue(all(n.startswith("gb_brainerd/") for n in names))

    def test_zip_data_acd_matches_source(self):
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "pc_civic"
            src.mkdir()
            (src / "data.acd").write_bytes(b"acd-bytes")
            dest = Path(raw) / "pc_civic.zip"
            pack_folder(src, dest)
            assert_zip_data_matches_source(src, dest)
            (src / "data.acd").write_bytes(b"different")
            with self.assertRaises(SystemExit):
                assert_zip_data_matches_source(src, dest)

    def test_skips_bak_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertTrue(should_skip(root / "data.acd.bak_blur", root))
            self.assertTrue(should_skip(root / "toyota_gr86_premium.kn5.bak_dx11", root))
            self.assertFalse(should_skip(root / "data.acd", root))

    def test_csp_cars_are_marked_in_catalog(self):
        self.assertTrue(car_requires_csp("pc_civic"))
        self.assertTrue(car_requires_csp("tbb_toyota_gr86_premium"))
        self.assertFalse(car_requires_csp("abarth_124_2016"))

    def test_cm_asset_url_picks_named_zip(self):
        url = content_manager_asset_url(
            {
                "assets": [
                    {"name": "Source.zip", "browser_download_url": "http://x/src.zip"},
                    {
                        "name": "Content.Manager.zip",
                        "browser_download_url": "http://x/Content.Manager.zip",
                    },
                ]
            }
        )
        self.assertEqual(url, "http://x/Content.Manager.zip")


if __name__ == "__main__":
    unittest.main()
