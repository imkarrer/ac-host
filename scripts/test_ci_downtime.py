import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ci_downtime
import pending_deploy


class DowntimeTests(unittest.TestCase):
    def test_apply_noop_without_pending(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            self.assertEqual(ci_downtime.apply_pending(state), "")

    def test_apply_syncs_pending_src(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state"
            src = root / "src"
            staged = state / "pending-src"
            (staged / "scripts").mkdir(parents=True)
            (staged / "scripts" / "hi.py").write_text("ok\n", encoding="utf-8")
            pending_deploy.write_pending({"sha": "abc123", "rebuild_sidecars": False}, state)
            with mock.patch.object(pending_deploy, "src_dir", return_value=src):
                sha = ci_downtime.apply_pending(state)
            self.assertEqual(sha, "abc123")
            self.assertTrue((src / "scripts" / "hi.py").is_file())
            self.assertIsNone(pending_deploy.load_pending(state))
            applied = pending_deploy.load_applied(state)
            assert applied is not None
            self.assertEqual(applied["sha"], "abc123")

    def test_main_skips_second_recycle_same_day(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            os.environ["AC_STATE"] = str(state)
            ci_downtime.write_stamp(state, "already")
            with mock.patch.object(ci_downtime, "recycle_static") as recycle:
                self.assertEqual(ci_downtime.main(), 0)
            recycle.assert_not_called()
            del os.environ["AC_STATE"]


if __name__ == "__main__":
    unittest.main()
