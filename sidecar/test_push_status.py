import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import push_status


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


def mock_urlopen_factory(*, puts: list | None = None, calls: list | None = None, captured: dict | None = None):
    def fake_urlopen(req, timeout=30):
        if req.get_method() == "PUT":
            payload = json.loads(req.data.decode("utf-8"))
            if puts is not None:
                puts.append(payload.get("message", ""))
            if calls is not None:
                calls.append(payload)
            if captured is not None:
                captured["url"] = req.full_url
                captured["headers"] = dict(req.header_items())
                captured["body"] = payload
            return FakeResponse(b"{}")
        return FakeResponse(json.dumps({"sha": "abc"}).encode("utf-8"))

    return fake_urlopen


class PushStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        push_status.reset_pusher()

    def tearDown(self) -> None:
        push_status.reset_pusher()

    def test_disabled_without_token(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            push_status.reset_pusher()
            pusher = push_status.get_pusher()
            self.assertFalse(pusher.enabled)
            pusher.schedule('{"updated": "x", "lobbies": {}}\n')

    def test_skips_unchanged_hash(self) -> None:
        env = {
            "GITHUB_STATUS_TOKEN": "test-token",
            "GITHUB_STATUS_REPO": "owner/repo",
            "GITHUB_STATUS_BRANCH": "main",
            "GITHUB_STATUS_PATH": "leaderboard.json",
            "GITHUB_STATUS_DEBOUNCE_SEC": "0.05",
        }
        text = json.dumps({"updated": "2026-01-01T00:00:00+00:00", "lobbies": {}}) + "\n"
        calls: list[dict] = []

        with patch.dict(os.environ, env, clear=False):
            push_status.reset_pusher()
            with patch.object(push_status, "urlopen", side_effect=mock_urlopen_factory(calls=calls)):
                pusher = push_status.get_pusher()
                pusher.flush_now(text)
                self.assertEqual(len(calls), 1)
                self.assertIn("content", calls[0])
                pusher.flush_now(text)
                self.assertEqual(len(calls), 1)

    def test_debounce_coalesces_burst(self) -> None:
        env = {
            "GITHUB_STATUS_TOKEN": "test-token",
            "GITHUB_STATUS_REPO": "owner/repo",
            "GITHUB_STATUS_BRANCH": "main",
            "GITHUB_STATUS_PATH": "leaderboard.json",
            "GITHUB_STATUS_DEBOUNCE_SEC": "0.1",
        }
        puts: list[str] = []

        with patch.dict(os.environ, env, clear=False):
            push_status.reset_pusher()
            with patch.object(push_status, "urlopen", side_effect=mock_urlopen_factory(puts=puts)):
                pusher = push_status.get_pusher()
                for i in range(5):
                    text = json.dumps({"updated": f"t{i}", "lobbies": {}}) + "\n"
                    pusher.schedule(text)
                time.sleep(0.35)
                self.assertEqual(len(puts), 1)
                self.assertIn("t4", puts[0])

    def test_put_payload_shape(self) -> None:
        env = {
            "GITHUB_STATUS_TOKEN": "secret",
            "GITHUB_STATUS_REPO": "me/ac-practice",
            "GITHUB_STATUS_BRANCH": "main",
            "GITHUB_STATUS_PATH": "leaderboard.json",
        }
        text = json.dumps({"updated": "2026-03-01T12:00:00+00:00", "lobbies": {}}) + "\n"
        captured: dict = {}

        with patch.dict(os.environ, env, clear=False):
            push_status.reset_pusher()
            with patch.object(push_status, "urlopen", side_effect=mock_urlopen_factory(captured=captured)):
                push_status.get_pusher().flush_now(text)
        self.assertIn("/repos/me/ac-practice/contents/leaderboard.json", captured["url"])
        self.assertIn("Bearer secret", captured["headers"]["Authorization"])
        self.assertEqual(captured["body"]["branch"], "main")
        self.assertEqual(captured["body"]["sha"], "abc")
        self.assertIn("content", captured["body"])

    def test_event_url_from_repo(self) -> None:
        env = {"GITHUB_STATUS_REPO": "imkarrer/ac-practice", "STATUS_EVENT_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(push_status.event_url(), "https://ntfy.sh/ac-imkarrer-ac-practice-status")
            self.assertEqual(
                push_status.event_sse_url(),
                "https://ntfy.sh/ac-imkarrer-ac-practice-status/sse",
            )

    def test_event_url_explicit(self) -> None:
        with patch.dict(os.environ, {"STATUS_EVENT_URL": "https://ntfy.sh/custom-topic"}, clear=False):
            self.assertEqual(push_status.event_url(), "https://ntfy.sh/custom-topic")
            self.assertEqual(push_status.event_sse_url(), "https://ntfy.sh/custom-topic/sse")

    def test_put_posts_status_event(self) -> None:
        env = {
            "GITHUB_STATUS_TOKEN": "secret",
            "GITHUB_STATUS_REPO": "me/ac-practice",
            "GITHUB_STATUS_BRANCH": "main",
            "GITHUB_STATUS_PATH": "leaderboard.json",
            "STATUS_EVENT_URL": "https://ntfy.sh/test-topic",
        }
        text = json.dumps({"updated": "2026-03-01T12:00:00+00:00", "lobbies": {}}) + "\n"
        posts: list[str] = []

        def fake_urlopen(req, timeout=30):
            if req.get_method() == "POST":
                posts.append(req.data.decode("utf-8"))
                self.assertEqual(req.full_url, "https://ntfy.sh/test-topic")
                return FakeResponse(b"{}")
            if req.get_method() == "PUT":
                return FakeResponse(b"{}")
            return FakeResponse(json.dumps({"sha": "abc"}).encode("utf-8"))

        with patch.dict(os.environ, env, clear=False):
            push_status.reset_pusher()
            with patch.object(push_status, "urlopen", side_effect=fake_urlopen):
                push_status.get_pusher().flush_now(text)
        self.assertEqual(posts, ["2026-03-01T12:00:00+00:00"])

    def test_heartbeat_posts_without_github_token(self) -> None:
        posts: list[str] = []

        def fake_urlopen(req, timeout=30):
            posts.append(req.data.decode("utf-8"))
            self.assertEqual(req.full_url, "https://ntfy.sh/test-topic")
            return FakeResponse(b"{}")

        env = {"STATUS_EVENT_URL": "https://ntfy.sh/test-topic", "GITHUB_STATUS_TOKEN": "", "GITHUB_STATUS_REPO": ""}
        with patch.dict(os.environ, env, clear=False):
            push_status.reset_pusher()
            with patch.object(push_status, "urlopen", side_effect=fake_urlopen):
                push_status.notify_heartbeat()
        self.assertEqual(posts, ["heartbeat"])


if __name__ == "__main__":
    unittest.main()
