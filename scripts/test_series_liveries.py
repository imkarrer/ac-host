#!/usr/bin/env python3
"""Tests for the race-pack pipeline: roster rules, naming, and the paint floor.

These cover everything up to the point where pixels get pushed around; the
compositing itself is proved by test_skin_livery.py and by each skin's own
offline render.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _path in (str(REPO / "shared"), str(REPO / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import generate_series_liveries as pack  # noqa: E402
import publish_series_race_pack as publish  # noqa: E402
import series_render  # noqa: E402
import skin_livery  # noqa: E402

CAR = "tbb_toyota_gr86_premium"
CONTENT = REPO.parent / "content"


def write_state(root: Path, drivers: list[dict], grid: list[dict] | None) -> None:
    series = root / "series" / "series-1"
    (series / "rounds").mkdir(parents=True, exist_ok=True)
    (series / "signups.json").write_text(
        json.dumps({"series_id": "series-1", "drivers": drivers}), encoding="utf-8"
    )
    (series / "rounds" / "r00.json").write_text(
        json.dumps({"series_id": "series-1", "round_id": "r00", "grid": grid or []}),
        encoding="utf-8",
    )


def driver(steam_id: str, name: str, number: str, skin: str) -> dict:
    return {
        "steam_id": steam_id,
        "discord_id": f"d{steam_id[-4:]}",
        "name": name,
        "car": CAR,
        "skin": skin,
        "number": number,
    }


class NamingTests(unittest.TestCase):
    def test_skin_name_is_deterministic(self):
        first = pack.output_skin_name("series-1", "787")
        second = pack.output_skin_name("series-1", "787")
        self.assertEqual(first, second)
        self.assertEqual(first, "series1_787")

    def test_name_has_no_round_in_it(self):
        # Numbers are frozen at signup close, so the same skin serves every round.
        # A round in the name would force a rebuild and a re-download each week.
        self.assertNotIn("r00", pack.output_skin_name("series-1", "7"))

    def test_series_do_not_collide(self):
        self.assertNotEqual(
            pack.output_skin_name("series-1", "7"), pack.output_skin_name("series-2", "7")
        )

    def test_name_is_a_safe_folder(self):
        # A number that arrives as something other than digits must not be able
        # to escape the skins directory.
        with self.assertRaises(ValueError):
            pack.output_skin_name("series-1", "../../evil")


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="packtest_"))
        self.state = self.tmp / "STATE"

    def test_roster_is_every_signup_and_needs_no_round(self):
        # The pack is built at signup close, before any round has a grid.
        drivers = [
            driver("76561198000000001", "a", "1", "03_raven"),
            driver("76561198000000002", "b", "2", "03_raven"),
        ]
        write_state(self.state, drivers, None)
        car, entries = pack.roster(
            state=self.state,
            catalog=REPO / "catalog",
            series_id="series-1",
            default_skin="",
        )
        self.assertEqual(car, CAR)
        self.assertEqual(sorted(e.name for e in entries), ["a", "b"])

    def test_missing_colour_falls_back_to_preferred_skin(self):
        write_state(self.state, [driver("76561198000000001", "a", "1", "")], None)
        _car, entries = pack.roster(
            state=self.state,
            catalog=REPO / "catalog",
            series_id="series-1",
            default_skin="",
        )
        self.assertEqual(entries[0].base_skin, "04_trueno_blue")

    def test_duplicate_numbers_are_rejected(self):
        entries = [
            pack.Entry(steam_id="1", name="a", number="7", base_skin="03_raven"),
            pack.Entry(steam_id="2", name="b", number="7", base_skin="03_raven"),
        ]
        with self.assertRaises(SystemExit) as ctx:
            pack.check_roster(entries, CONTENT, CAR)
        self.assertIn("claimed by both", str(ctx.exception))

    def test_missing_number_is_rejected(self):
        entries = [pack.Entry(steam_id="1", name="a", number="", base_skin="03_raven")]
        with self.assertRaises(SystemExit) as ctx:
            pack.check_roster(entries, CONTENT, CAR)
        self.assertIn("has no number", str(ctx.exception))

    def test_out_of_range_number_is_rejected(self):
        entries = [pack.Entry(steam_id="1", name="a", number="1000", base_skin="03_raven")]
        with self.assertRaises(SystemExit):
            pack.check_roster(entries, CONTENT, CAR)

    @unittest.skipUnless((CONTENT / "cars" / CAR).is_dir(), "car content not installed")
    def test_unknown_base_skin_is_rejected(self):
        entries = [pack.Entry(steam_id="1", name="a", number="7", base_skin="no_such_colour")]
        with self.assertRaises(SystemExit) as ctx:
            pack.check_roster(entries, CONTENT, CAR)
        self.assertIn("not in content", str(ctx.exception))


class ChunkTests(unittest.TestCase):
    @staticmethod
    def entries(*colours: str) -> list[pack.Entry]:
        return [
            pack.Entry(steam_id=str(i), name=f"d{i}", number=str(i + 1), base_skin=colour)
            for i, colour in enumerate(colours)
        ]

    def test_one_chunk_per_colour_when_sequential(self):
        chunks = pack.plan_chunks(self.entries("a", "b", "a", "b", "c"), jobs=1)
        self.assertEqual(sorted(c for c, _ in chunks), ["a", "b", "c"])

    def test_every_driver_is_built_exactly_once(self):
        entries = self.entries(*(["a"] * 12 + ["b"] * 8))
        for jobs in (1, 2, 4, 8, 16):
            built = [e.steam_id for _c, drivers in pack.plan_chunks(entries, jobs) for e in drivers]
            self.assertEqual(sorted(built, key=int), [e.steam_id for e in entries])

    def test_big_colour_group_splits_for_workers(self):
        chunks = pack.plan_chunks(self.entries(*(["a"] * 20)), jobs=4)
        self.assertEqual(len(chunks), 4)
        self.assertTrue(all(c == "a" for c, _ in chunks))

    def test_small_groups_are_not_split_into_uneconomic_chunks(self):
        # Splitting would make each worker re-parse the kn5 for one or two cars.
        chunks = pack.plan_chunks(self.entries("a", "a", "b", "b"), jobs=16)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(d) >= pack.MIN_CHUNK - 1 for _c, d in chunks))


class PaintFloorTests(unittest.TestCase):
    """A pure black paint cannot be baked by multiplying — see bakeable_tint."""

    def test_black_is_lifted_off_zero(self):
        lifted = skin_livery.bakeable_tint((0, 0, 0))
        self.assertEqual(lifted, (24, 24, 24))

    def test_lift_keeps_hue(self):
        lifted = skin_livery.bakeable_tint((4, 0, 2))
        self.assertEqual(lifted[1], 0)
        self.assertGreater(lifted[0], lifted[2])
        self.assertEqual(max(lifted), skin_livery.BAKE_TINT_FLOOR)

    def test_normal_paint_is_untouched(self):
        for tint in ((183, 0, 0), (1, 21, 76), (61, 61, 61), (255, 255, 255)):
            self.assertEqual(skin_livery.bakeable_tint(tint), tint)

    def test_lifted_black_survives_the_colour_check(self):
        tint = skin_livery.bakeable_tint((0, 0, 0))
        baked = tuple(int(c * 0.42) for c in tint)
        hue_error, brightness = skin_livery._tint_match(tint, baked)  # type: ignore[arg-type]
        self.assertLessEqual(hue_error, 24)
        self.assertGreaterEqual(brightness, 0.2)


class PublishVersionTests(unittest.TestCase):
    """The version decides whether 20 drivers re-download a 300 MB zip."""

    @staticmethod
    def manifest(*drivers: tuple[str, str]) -> dict:
        return {
            "car": CAR,
            "drivers": [{"race_skin": skin, "sha256": digest} for skin, digest in drivers],
        }

    def test_same_pack_gives_the_same_version(self):
        one = self.manifest(("series1_7", "aa"), ("series1_9", "bb"))
        two = self.manifest(("series1_7", "aa"), ("series1_9", "bb"))
        self.assertEqual(
            publish.series_version(one, "2.0.1", "series-1"),
            publish.series_version(two, "2.0.1", "series-1"),
        )

    def test_driver_order_does_not_change_the_version(self):
        one = self.manifest(("series1_7", "aa"), ("series1_9", "bb"))
        two = self.manifest(("series1_9", "bb"), ("series1_7", "aa"))
        self.assertEqual(
            publish.series_version(one, "2.0.1", "series-1"),
            publish.series_version(two, "2.0.1", "series-1"),
        )

    def test_changed_skin_changes_the_version(self):
        one = self.manifest(("series1_7", "aa"))
        two = self.manifest(("series1_7", "cc"))
        self.assertNotEqual(
            publish.series_version(one, "2.0.1", "series-1"),
            publish.series_version(two, "2.0.1", "series-1"),
        )

    def test_added_driver_changes_the_version(self):
        one = self.manifest(("series1_7", "aa"))
        two = self.manifest(("series1_7", "aa"), ("series1_9", "bb"))
        self.assertNotEqual(
            publish.series_version(one, "2.0.1", "series-1"),
            publish.series_version(two, "2.0.1", "series-1"),
        )

    def test_suffixes_do_not_accumulate_across_republishes(self):
        first = publish.series_version(self.manifest(("series1_7", "aa")), "2.0.1", "series-1")
        second = publish.series_version(self.manifest(("series1_7", "bb")), first, "series-1")
        self.assertEqual(second.count("series1"), 1)
        self.assertTrue(second.startswith("2.0.1-series1-"))

    def test_base_version_survives(self):
        version = publish.series_version(self.manifest(("series1_7", "aa")), "2.0.1", "series-1")
        self.assertEqual(publish.base_version(version), "2.0.1")


class RaceEntryListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="packtest_"))
        self.state = self.tmp / "STATE"

    def test_race_phase_uses_the_numbered_skin_from_the_signup(self):
        # The grid is built at quali close and knows nothing about the pack, so
        # the race entry list has to pick race_skin up from the signup row.
        signup = driver("76561198000000001", "a", "7", "03_raven")
        signup["race_skin"] = "series1_7"
        grid = [{"pos": 1, "steam_id": "76561198000000001", "skin": "03_raven"}]
        write_state(self.state, [signup], grid)
        got = series_render.load_drivers_for_phase(
            state=self.state,
            catalog=REPO / "catalog",
            series_id="series-1",
            round_id="r00",
            phase="race",
        )
        self.assertEqual(got[0]["skin"], "series1_7")

    def test_race_falls_back_to_signup_colour_without_a_pack(self):
        drivers = [driver("76561198000000001", "a", "7", "03_raven")]
        grid = [{"pos": 1, "steam_id": "76561198000000001", "skin": "03_raven"}]
        write_state(self.state, drivers, grid)
        got = series_render.load_drivers_for_phase(
            state=self.state,
            catalog=REPO / "catalog",
            series_id="series-1",
            round_id="r00",
            phase="race",
        )
        self.assertEqual(got[0]["skin"], "03_raven")

    def test_quali_never_uses_the_numbered_skin(self):
        signup = driver("76561198000000001", "a", "7", "03_raven")
        signup["race_skin"] = "series1_7"
        grid = [{"pos": 1, "steam_id": "76561198000000001", "skin": "03_raven"}]
        write_state(self.state, [signup], grid)
        got = series_render.load_drivers_for_phase(
            state=self.state,
            catalog=REPO / "catalog",
            series_id="series-1",
            round_id="r00",
            phase="quali",
        )
        self.assertEqual(got[0]["skin"], "03_raven")


if __name__ == "__main__":
    unittest.main(verbosity=1)
