import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ci_queue_prod
import pending_deploy


class QueueProdTests(unittest.TestCase):
    def _queue(self, state: Path, applied: dict, changed: list[str]) -> dict:
        pending_deploy.write_applied(applied, state)
        env = {"AC_STATE": str(state), "BUILDKITE_COMMIT": "new0000"}
        with mock.patch.dict(os.environ, env), mock.patch.object(
            pending_deploy, "git_changed_paths", return_value=changed
        ), mock.patch.object(pending_deploy, "sync_tree"):
            self.assertEqual(ci_queue_prod.main(), 0)
        pending = pending_deploy.load_pending(state)
        assert pending is not None
        return pending

    def test_owed_recreate_is_carried_to_the_next_queue(self) -> None:
        # The last apply wanted a recreate and skipped it (image missing). This
        # diff touches nothing sidecar-related, yet the recreate is still owed.
        with tempfile.TemporaryDirectory() as raw:
            pending = self._queue(
                Path(raw),
                {"sha": "old0000", "rebuild_sidecars": True, "sidecars_recreated": False},
                ["site/app.js"],
            )
        self.assertTrue(pending["rebuild_sidecars"])

    def test_completed_recreate_does_not_rearm(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pending = self._queue(
                Path(raw),
                {"sha": "old0000", "rebuild_sidecars": True, "sidecars_recreated": True},
                ["site/app.js"],
            )
        self.assertFalse(pending["rebuild_sidecars"])

    def test_stamp_without_the_key_is_trusted(self) -> None:
        # Stamps written before sidecars_recreated existed came from a path that
        # never skipped, so their absence of the key means "done".
        with tempfile.TemporaryDirectory() as raw:
            pending = self._queue(Path(raw), {"sha": "old0000", "rebuild_sidecars": True}, ["site/app.js"])
        self.assertFalse(pending["rebuild_sidecars"])

    def test_missing_state_dir_skips_green_and_stages_nothing(self) -> None:
        # An agent that cannot see the tenant's state must not fail the build
        # and must not stage anything. The skip line names what it checked --
        # the directory and the variable naming it -- rather than guessing a host.
        with tempfile.TemporaryDirectory() as raw:
            missing = Path(raw) / "no-such-state"
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"AC_STATE": str(missing)}), mock.patch.object(
                pending_deploy, "sync_tree"
            ) as sync, contextlib.redirect_stdout(out):
                self.assertEqual(ci_queue_prod.main(), 0)
            sync.assert_not_called()
            self.assertFalse(missing.exists())
        self.assertIn(f"skip queue-prod: {missing} (AC_STATE) is not a directory", out.getvalue())


if __name__ == "__main__":
    unittest.main()
