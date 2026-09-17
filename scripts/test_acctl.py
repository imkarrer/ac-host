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

    def test_ensure_sidecar_image_passes_when_present(self) -> None:
        with patch.object(acctl, "docker_image_exists", return_value=True):
            acctl.ensure_sidecar_image()

    def test_ensure_sidecar_image_fails_loudly_when_missing(self) -> None:
        # acctl cannot build it (flox is not on the box), so it must say where it comes from.
        with patch.object(acctl, "docker_image_exists", return_value=False), patch.object(
            acctl, "compose"
        ) as mock_compose:
            with self.assertRaises(SystemExit) as ctx:
                acctl.ensure_sidecar_image()
            mock_compose.assert_not_called()
        self.assertIn("ac-host-env:latest", str(ctx.exception))
        self.assertIn("ci_containerize.sh", str(ctx.exception))

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
