import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pending_deploy
import buildkite_trigger


class PendingDeployTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            pending_deploy.write_pending({"sha": "abc", "rebuild_sidecars": True}, state)
            loaded = pending_deploy.load_pending(state)
            assert loaded is not None
            self.assertEqual(loaded["sha"], "abc")
            self.assertTrue(loaded["rebuild_sidecars"])
            pending_deploy.clear_pending(state)
            self.assertIsNone(pending_deploy.load_pending(state))

    def test_rebuild_from_sidecar_paths(self) -> None:
        self.assertTrue(pending_deploy.rebuild_sidecars_from_diff(["sidecar/plugin.py"]))
        self.assertTrue(pending_deploy.rebuild_sidecars_from_diff(["bot/bot.py"]))
        self.assertTrue(pending_deploy.rebuild_sidecars_from_diff(["compose/docker-compose.yml"]))
        self.assertFalse(pending_deploy.rebuild_sidecars_from_diff(["scripts/acctl.py", "site/app.js"]))

    def test_sync_tree_skips_cache_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "src"
            dest = Path(raw) / "dest"
            (src / "scripts").mkdir(parents=True)
            (src / "scripts" / "hi.py").write_text("x\n", encoding="utf-8")
            (src / ".env").write_text("SECRET=1\n", encoding="utf-8")
            (src / ".flox" / "cache").mkdir(parents=True)
            (src / ".flox" / "cache" / "junk").write_text("n\n", encoding="utf-8")
            (src / ".flox" / "env.json").write_text("{}\n", encoding="utf-8")
            pending_deploy.sync_tree(src, dest)
            self.assertTrue((dest / "scripts" / "hi.py").is_file())
            self.assertTrue((dest / ".flox" / "env.json").is_file())
            self.assertFalse((dest / ".env").exists())
            self.assertFalse((dest / ".flox" / "cache").exists())

    def test_sync_tree_preserves_local_dist_artifacts(self) -> None:
        """dist/*.zip and dist/content.json are gitignored box state, like the
        hardware-configuration.nix / ssh-keys.local.nix case: pending-src can
        never contain them, so rsync --delete must not remove them either."""
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "src"
            dest = Path(raw) / "dest"
            (src / "scripts").mkdir(parents=True)
            (src / "scripts" / "hi.py").write_text("x\n", encoding="utf-8")
            (dest / "dist").mkdir(parents=True)
            (dest / "dist" / "abarth_124_2016.zip").write_text("car\n", encoding="utf-8")
            (dest / "dist" / "content.json").write_text("{}\n", encoding="utf-8")
            pending_deploy.sync_tree(src, dest)
            self.assertTrue((dest / "scripts" / "hi.py").is_file())
            self.assertTrue((dest / "dist" / "abarth_124_2016.zip").is_file())
            self.assertTrue((dest / "dist" / "content.json").is_file())


class BuildkiteTriggerTests(unittest.TestCase):
    def test_payload_includes_series_env(self) -> None:
        payload = buildkite_trigger.build_payload(
            message="series pack",
            env={"SERIES_ID": "series-1", "ROUND_ID": "r00"},
        )
        self.assertEqual(payload["commit"], "HEAD")
        self.assertEqual(payload["env"]["SERIES_ID"], "series-1")

    def test_downtime_payload(self) -> None:
        payload = buildkite_trigger.build_payload(
            message="03:00 apply + recycle",
            env={"DOWNTIME": "1"},
        )
        self.assertEqual(payload["env"]["DOWNTIME"], "1")
        self.assertNotIn("SERIES_ID", payload["env"])

    def test_configured(self) -> None:
        self.assertFalse(buildkite_trigger.configured(token="", org="imkarrer", pipeline="ac-host"))
        self.assertTrue(
            buildkite_trigger.configured(token="bkua_x", org="imkarrer", pipeline="ac-host")
        )

    def test_pipeline_slugs(self) -> None:
        saved = {
            key: os.environ.pop(key, None)
            for key in ("BUILDKITE_PIPELINE", "BUILDKITE_PIPELINE_OPS", "BUILDKITE_PIPELINE_SERIES")
        }
        try:
            self.assertEqual(buildkite_trigger.pipeline_slug("ci"), "ac-host")
            self.assertEqual(buildkite_trigger.pipeline_slug("ops"), "ac-host-ops")
            self.assertEqual(buildkite_trigger.pipeline_slug("series"), "ac-host-series")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class WipeBackupTests(unittest.TestCase):
    """sync_tree must be recoverable, not merely careful.

    Dry-running the first ever sync found five separate categories of
    machine-local state it would have destroyed. Each got an exclude once known.
    The snapshot exists because the list of things nobody thought to exclude is
    never knowably empty.
    """

    @unittest.skipIf(shutil.which("rsync") is None, "needs rsync")
    def test_deleted_and_overwritten_files_land_in_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state, src, dest = root / "state", root / "pending-src", root / "src"
            src.mkdir()
            dest.mkdir()
            (src / "a.txt").write_text("new")
            # Different size AND an older mtime on purpose: rsync's quick-check
            # is size+mtime, so same-size files written in the same second are
            # skipped entirely and never backed up. An earlier version of this
            # test silently proved nothing for that reason.
            (dest / "a.txt").write_text("old, and longer")
            os.utime(dest / "a.txt", (1_000_000, 1_000_000))
            (dest / "gone.txt").write_text("precious")

            snapshot = pending_deploy.sync_tree(src, dest)

            self.assertIsNotNone(snapshot)
            self.assertEqual((snapshot / "gone.txt").read_text(), "precious")
            self.assertEqual((snapshot / "a.txt").read_text(), "old, and longer")
            self.assertEqual((dest / "a.txt").read_text(), "new")
            self.assertFalse((dest / "gone.txt").exists())

    @unittest.skipIf(shutil.which("rsync") is None, "needs rsync")
    def test_two_syncs_in_one_second_get_separate_snapshots(self) -> None:
        # utcnow() is second-resolution; without a uniquifying suffix the second
        # sync reused the first snapshot directory, which also defeated the
        # empty-snapshot cleanup.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state, src, dest = root / "state", root / "pending-src", root / "src"
            src.mkdir()
            dest.mkdir()
            (src / "a.txt").write_text("x")
            (dest / "doomed.txt").write_text("first")

            first = pending_deploy.sync_tree(src, dest)
            (dest / "doomed2.txt").write_text("second")
            second = pending_deploy.sync_tree(src, dest)

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertNotEqual(first, second)
            self.assertEqual((first / "doomed.txt").read_text(), "first")
            self.assertEqual((second / "doomed2.txt").read_text(), "second")

    @unittest.skipIf(shutil.which("rsync") is None, "needs rsync")
    def test_a_sync_that_changes_nothing_leaves_no_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state, src, dest = root / "state", root / "pending-src", root / "src"
            src.mkdir()
            dest.mkdir()
            (src / "a.txt").write_text("same")
            pending_deploy.sync_tree(src, dest)

            self.assertIsNone(pending_deploy.sync_tree(src, dest))

    def test_prune_keeps_the_newest_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "src"
            backups = pending_deploy.wipe_backup_root(dest)
            for day in range(8):
                (backups / f"2026010{day}T000000Z").mkdir(parents=True)

            removed = pending_deploy.prune_wipe_backups(dest, keep=5)

            kept = sorted(p.name for p in backups.iterdir())
            self.assertEqual(len(kept), 5)
            self.assertEqual(len(removed), 3)
            self.assertIn("20260107T000000Z", kept)
            self.assertNotIn("20260100T000000Z", kept)

    def test_backup_root_sits_outside_the_synced_tree(self) -> None:
        # If snapshots lived inside dest, rsync would recurse into its own
        # backups. _local_wipe_backup/ is in RSYNC_EXCLUDES for that reason, but
        # keeping them out of the tree entirely is the stronger guarantee.
        state = Path("/var/lib/ac-host")
        self.assertEqual(
            pending_deploy.wipe_backup_root(state / "src"), state / "_local_wipe_backup"
        )
        self.assertFalse(
            str(pending_deploy.wipe_backup_root(state / "src")).startswith(str(state / "src"))
        )


if __name__ == "__main__":
    unittest.main()
