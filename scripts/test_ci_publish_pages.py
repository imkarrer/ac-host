import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_publish_pages as pub


class BlobShaTests(unittest.TestCase):
    def test_matches_git_hash_object(self) -> None:
        # Publishing runs on every green build and skips a file whose blob id
        # already matches what GitHub holds. If this drifts from git's own
        # object id nothing ever matches, and every build rewrites all of
        # ALLOWED -- so pin it against git itself rather than a fixture.
        samples = [b"", b"hello\n", b"\x00\x01binary\xff", "unicode ✓\n".encode("utf-8")]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for i, data in enumerate(samples):
                path = root / f"sample{i}"
                path.write_bytes(data)
                expected = subprocess.run(
                    ["git", "hash-object", str(path)],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                self.assertEqual(pub.blob_sha(data), expected, f"sample {i}")


class PushEnabledTests(unittest.TestCase):
    def test_only_explicit_truthy_values_publish(self) -> None:
        import os
        from unittest.mock import patch

        for value, want in (("1", True), ("true", True), ("yes", True),
                            ("0", False), ("", False), ("no", False)):
            with patch.dict(os.environ, {"AC_PAGES_PUSH": value}, clear=False):
                self.assertEqual(pub.push_enabled(), want, f"AC_PAGES_PUSH={value!r}")


class AllowedTests(unittest.TestCase):
    def test_leaderboard_is_not_publishable(self) -> None:
        # The live board is written by the plugin through the same repo. If it
        # ever entered ALLOWED a publish would overwrite real lap rows with
        # whatever the render produced.
        self.assertNotIn("leaderboard.json", pub.ALLOWED)


if __name__ == "__main__":
    unittest.main()
