import unittest
from unittest.mock import patch

import acctl


class AcctlHelpersTests(unittest.TestCase):
    def test_sidecar_up_never_builds(self) -> None:
        # No Dockerfile exists for the sidecars any more; the image is CI's.
        self.assertEqual(acctl.sidecar_up_args("auth", recreate=False), ["up", "-d", "auth"])
        self.assertEqual(
            acctl.sidecar_up_args("plugin", recreate=True), ["up", "-d", "--force-recreate", "plugin"]
        )
        for service in ("auth", "plugin", "details"):
            for recreate in (False, True):
                self.assertNotIn("--build", acctl.sidecar_up_args(service, recreate=recreate))

    def test_sidecar_image_is_the_flox_image(self) -> None:
        self.assertEqual(acctl.SIDECAR_IMAGE, "ac-host-env:latest")

    def _up_static(self, *, sidecar_image: bool):
        """Run cmd_up_static with docker stubbed; returns (manager, stderr)."""
        import io
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        lobby = {"id": "x", "slot": 1, "track": "magione", "name": "X"}
        exists = lambda name: sidecar_image if name == acctl.SIDECAR_IMAGE else True  # noqa: E731
        manager = MagicMock()
        err = io.StringIO()
        with patch.object(acctl, "docker_image_exists", side_effect=exists), patch.object(
            acctl, "compose", manager.compose
        ), patch.object(acctl, "run_server_container", manager.run_server_container), patch.object(
            acctl, "render"
        ), patch.object(acctl, "unifi_open_slot"), patch.object(acctl, "sync_site_content"), patch.object(
            acctl, "selected_statics", return_value=[lobby]
        ), patch.object(acctl, "wait_lobby_http"), patch.object(acctl, "publish_health"), patch.object(
            acctl, "dist_dir", return_value=acctl.Path("/nonexistent")
        ), patch("sys.stderr", err):
            acctl.cmd_up_static(SimpleNamespace(only=None, recreate=False))
        return manager, err.getvalue()

    def test_up_static_without_sidecar_image_still_starts_lobbies(self) -> None:
        # up-static is ac-host-static's ExecStart; a missing SIDECAR image must
        # never mean no race servers, and must not fail the unit (exit 0).
        manager, err = self._up_static(sidecar_image=False)
        manager.run_server_container.assert_called_once()
        manager.compose.assert_not_called()
        self.assertIn("ac-host-env:latest", err)
        self.assertIn("ci_containerize.sh", err)

    def test_up_static_starts_lobbies_before_sidecars(self) -> None:
        manager, _ = self._up_static(sidecar_image=True)
        names = [c[0] for c in manager.mock_calls]
        self.assertEqual(names[0], "run_server_container")
        self.assertEqual(names[1:], ["compose", "compose", "compose"])
        services = [c.args[-1] for c in manager.compose.call_args_list]
        self.assertEqual(services, ["auth", "plugin", "details"])
        for c in manager.compose.call_args_list:
            self.assertNotIn("--build", c.args)

    def test_ensure_image_skips_when_present(self) -> None:
        with patch.object(acctl, "docker_image_exists", return_value=True), patch.object(
            acctl, "compose"
        ) as mock_compose:
            acctl.ensure_image()
            mock_compose.assert_not_called()

    def test_ensure_image_builds_when_missing(self) -> None:
        # The Kunos server image (image/Dockerfile) is the one build compose still does.
        with patch.object(acctl, "docker_image_exists", return_value=False), patch.object(
            acctl, "compose"
        ) as mock_compose:
            acctl.ensure_image()
            mock_compose.assert_called_once_with("--profile", "build", "build", "static")


if __name__ == "__main__":
    unittest.main()
