import unittest
from unittest.mock import patch

import acctl


class AcctlHelpersTests(unittest.TestCase):
    def test_sidecar_up_skips_build_by_default(self) -> None:
        self.assertEqual(acctl.sidecar_up_args("auth", rebuild=False), ["up", "-d", "auth"])
        self.assertEqual(acctl.sidecar_up_args("plugin", rebuild=True), ["up", "-d", "--build", "plugin"])

    def test_ensure_image_skips_when_present(self) -> None:
        with patch.object(acctl, "docker_image_exists", return_value=True), patch.object(
            acctl, "compose"
        ) as mock_compose:
            acctl.ensure_image()
            mock_compose.assert_not_called()

    def test_ensure_image_builds_when_missing(self) -> None:
        with patch.object(acctl, "docker_image_exists", return_value=False), patch.object(
            acctl, "compose"
        ) as mock_compose:
            acctl.ensure_image()
            mock_compose.assert_called_once_with("--profile", "build", "build", "static")


if __name__ == "__main__":
    unittest.main()
