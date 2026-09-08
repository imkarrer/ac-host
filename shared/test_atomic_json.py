import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import atomic_json


class ReadJsonTests(unittest.TestCase):
    def test_absent_file_is_none_not_empty(self) -> None:
        # The distinction the whole module exists for: absent means "nothing yet",
        # unreadable means "do not touch". Collapsing both to {} is what erased
        # the leaderboard.
        with TemporaryDirectory() as raw:
            self.assertIsNone(atomic_json.read_json(Path(raw) / "nope.json"))

    def test_unreadable_raises_rather_than_returning_empty(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "board.json"
            path.write_text("{ this is not json", encoding="utf-8")
            with self.assertRaises(atomic_json.UnreadableJSON):
                atomic_json.read_json(path)

    def test_non_object_json_is_unreadable(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "board.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(atomic_json.UnreadableJSON):
                atomic_json.read_json(path)

    def test_roundtrip(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "board.json"
            atomic_json.write_json(path, {"drivers": [{"name": "a", "best": 91.2}]})
            self.assertEqual(
                atomic_json.read_json(path), {"drivers": [{"name": "a", "best": 91.2}]}
            )


class WriteJsonTests(unittest.TestCase):
    def test_replaces_existing_content(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "board.json"
            atomic_json.write_json(path, {"v": 1})
            atomic_json.write_json(path, {"v": 2})
            self.assertEqual(atomic_json.read_json(path), {"v": 2})

    def test_creates_parent_directories(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "dist" / "deep" / "board.json"
            atomic_json.write_json(path, {"ok": True})
            self.assertTrue(path.is_file())

    def test_leaves_no_temp_files_behind(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "board.json"
            atomic_json.write_json(path, {"v": 1})
            leftovers = [p.name for p in Path(raw).iterdir() if p.name != "board.json"]
            self.assertEqual(leftovers, [])

    def test_the_old_file_survives_a_failed_write(self) -> None:
        # The property that makes this atomic: a reader sees either the complete
        # old file or the complete new one. Simulated by making serialisation
        # fail, which is the one step that happens before any rename.
        with TemporaryDirectory() as raw:
            path = Path(raw) / "board.json"
            atomic_json.write_json(path, {"standings": "precious"})

            class Unserialisable:
                pass

            with self.assertRaises(TypeError):
                atomic_json.write_json(path, {"bad": Unserialisable()})

            self.assertEqual(atomic_json.read_json(path), {"standings": "precious"})
            leftovers = [p.name for p in Path(raw).iterdir() if p.name != "board.json"]
            self.assertEqual(leftovers, [])

    def test_temp_file_shares_the_destination_directory(self) -> None:
        # os.replace is only atomic within one filesystem, so the temp file must
        # not land in /tmp when the destination is elsewhere.
        with TemporaryDirectory() as raw:
            dest = Path(raw) / "sub"
            dest.mkdir()
            path = dest / "board.json"
            seen: list[str] = []
            real_mkstemp = atomic_json.tempfile.mkstemp

            def spy(*args, **kwargs):
                seen.append(kwargs.get("dir", ""))
                return real_mkstemp(*args, **kwargs)

            atomic_json.tempfile.mkstemp = spy
            try:
                atomic_json.write_json(path, {"v": 1})
            finally:
                atomic_json.tempfile.mkstemp = real_mkstemp
            self.assertEqual(seen, [str(dest)])


if __name__ == "__main__":
    unittest.main()
