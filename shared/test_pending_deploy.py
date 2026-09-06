import os
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


if __name__ == "__main__":
    unittest.main()
