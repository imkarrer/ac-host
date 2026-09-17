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

    def test_skipped_recreate_is_recorded_in_the_applied_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state"
            src = root / "src"
            staged = state / "pending-src"
            (staged / "scripts").mkdir(parents=True)
            pending_deploy.write_pending({"sha": "abc123", "rebuild_sidecars": True}, state)
            with mock.patch.object(pending_deploy, "src_dir", return_value=src), mock.patch.object(
                ci_downtime, "_recreate_sidecars", return_value=False
            ) as recreate:
                ci_downtime.apply_pending(state)
            recreate.assert_called_once()
            applied = pending_deploy.load_applied(state)
            assert applied is not None
            self.assertTrue(applied["rebuild_sidecars"])
            self.assertFalse(applied["sidecars_recreated"])
            # ...and a recreate that ran, or was never wanted, reads as done.
            pending_deploy.write_pending({"sha": "def456", "rebuild_sidecars": True}, state)
            with mock.patch.object(pending_deploy, "src_dir", return_value=src), mock.patch.object(
                ci_downtime, "_recreate_sidecars", return_value=True
            ):
                ci_downtime.apply_pending(state)
            self.assertTrue((pending_deploy.load_applied(state) or {})["sidecars_recreated"])
            pending_deploy.write_pending({"sha": "789abc", "rebuild_sidecars": False}, state)
            with mock.patch.object(pending_deploy, "src_dir", return_value=src), mock.patch.object(
                ci_downtime, "_recreate_sidecars"
            ) as recreate:
                ci_downtime.apply_pending(state)
            recreate.assert_not_called()
            self.assertTrue((pending_deploy.load_applied(state) or {})["sidecars_recreated"])

    def test_recreate_never_builds_and_needs_the_ci_image(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            src = root / "src"
            state = root / "state"
            (src / "compose").mkdir(parents=True)
            (src / "compose" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
            state.mkdir()
            (state / ".env").write_text("X=1\n", encoding="utf-8")
            # Image present: every compose call is a recreate, never a build.
            with mock.patch.object(pending_deploy, "docker_image_exists", return_value=True), mock.patch.object(
                ci_downtime.subprocess, "run"
            ) as run:
                self.assertTrue(ci_downtime._recreate_sidecars(src, state))
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                argv = call.args[0]
                self.assertNotIn("--build", argv)
                self.assertIn("--force-recreate", argv)
            # Image missing: nothing on the box can make it, so nothing is touched.
            with mock.patch.object(pending_deploy, "docker_image_exists", return_value=False), mock.patch.object(
                ci_downtime.subprocess, "run"
            ) as run:
                self.assertFalse(ci_downtime._recreate_sidecars(src, state))
            run.assert_not_called()

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
