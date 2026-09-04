#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docker_name_exporter as exp


class DockerNameExporterTests(unittest.TestCase):
    def test_docker_name_strips_slash(self) -> None:
        self.assertEqual(exp.docker_name(["/ac-static-blackhawk"]), "ac-static-blackhawk")
        self.assertEqual(exp.docker_name([]), "")

    def test_cadvisor_id(self) -> None:
        self.assertEqual(
            exp.cadvisor_id("f6677cdab071a915"),
            "/system.slice/docker-f6677cdab071a915.scope",
        )

    def test_render_metrics(self) -> None:
        text = exp.render_metrics(
            [
                {"Id": "abc123", "Names": ["/ac-static-gingerman"]},
                {"Id": "", "Names": ["/skip"]},
                {"Id": 'x"y', "Names": ['/bad"name']},
            ]
        )
        self.assertIn(
            'docker_container_info{id="/system.slice/docker-abc123.scope",'
            'container="ac-static-gingerman"} 1',
            text,
        )
        self.assertNotIn("skip", text)
        self.assertIn('container="bad\\"name"', text)


if __name__ == "__main__":
    unittest.main()
