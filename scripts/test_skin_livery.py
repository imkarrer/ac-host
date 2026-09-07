#!/usr/bin/env python3
"""Tests for KN5-driven race number generation.

Run:  py -3 scripts/test_skin_livery.py
Add:  --slow  to also build and validate a real numbered skin end to end.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "shared"
sys.path.insert(0, str(SHARED))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import kn5  # noqa: E402
import skin_livery  # noqa: E402
import skin_uv  # noqa: E402

CONTENT = REPO.parent / "content"
MIATA = "ks_mazda_miata"
MIATA_SKIN = "05_sunburst_yellow"
CATALOG = REPO / "catalog"
SLOW = "--slow" in sys.argv


def miata_or_skip(test: unittest.TestCase) -> skin_livery.BodyTarget:
    if not skin_livery.skin_dir(CONTENT, MIATA, MIATA_SKIN).is_dir():
        test.skipTest("Miata not installed")
    return skin_livery.load_body_target(CONTENT, MIATA)


class Kn5ParserTests(unittest.TestCase):
    def test_parse_consumes_whole_file(self) -> None:
        """Trailing bytes mean the node walk drifted and the UVs are garbage."""
        target = miata_or_skip(self)
        self.assertEqual(target.model.trailing_bytes, 0)

    def test_uvs_present_and_in_range(self) -> None:
        target = miata_or_skip(self)
        body = next(m for m in target.meshes if m.uvs)
        uvs = np.asarray(body.uvs)
        self.assertTrue((np.abs(uvs) <= 8.0).all())
        self.assertEqual(len(body.indices) % 3, 0)


class BodyDiscoveryTests(unittest.TestCase):
    def test_picks_body_diffuse_not_livery_png(self) -> None:
        """The regression that made numbers invisible: livery.png is only an icon."""
        target = miata_or_skip(self)
        self.assertEqual(target.material, "ext_chassis")
        self.assertEqual(target.texture, "Skin_00.dds")
        self.assertNotEqual(target.texture, "livery.png")
        self.assertGreaterEqual(min(target.texture_size), skin_livery.MIN_LIVERY_TEXTURE)

    def test_detail_slot_found(self) -> None:
        target = miata_or_skip(self)
        self.assertEqual(skin_livery.detail_texture_name(target), "metal_detail.dds")

    def test_tiling_paint_car_is_rejected(self) -> None:
        if not (CONTENT / "cars" / "abarth_124_2016").is_dir():
            self.skipTest("124 not installed")
        target = skin_livery.load_body_target(CONTENT, "abarth_124_2016")
        with self.assertRaises(ValueError):
            skin_livery.assert_paintable(target)


class VConventionTests(unittest.TestCase):
    """Lock the stored-V rule against evidence outside the placement maths.

    Reading V as -v instead of v mod 1 mirrors the layout vertically. The mask
    and the offline render both used the same rule, so both looked right while
    the game put the Miata's numbers on the hood and the rear bumper.
    """

    PLATE_CARS = ("ks_toyota_gt86", "tbb_toyota_gr86_premium", "abarth_124_2016")

    def test_plate_anchor_agrees_with_code(self) -> None:
        checked = 0
        for car in self.PLATE_CARS:
            if not (CONTENT / "cars" / car).is_dir():
                continue
            model = kn5.read_kn5(skin_livery.find_car_kn5(CONTENT, car))
            convention, strength = skin_uv.detect_v_convention(model)
            if strength < skin_livery.V_ANCHOR_MIN_STRENGTH:
                continue
            checked += 1
            self.assertEqual(convention, skin_uv.V_CONVENTION, f"{car} disagrees")
        if not checked:
            self.skipTest("no car with a usable plate anchor installed")

    def test_flip_v_wraps_rather_than_negates(self) -> None:
        got = skin_uv._flip_v(np.array([-0.669, -0.331, -0.01, 0.25], dtype=np.float32))
        np.testing.assert_allclose(got, [0.331, 0.669, 0.99, 0.25], atol=1e-5)


class HandednessTests(unittest.TestCase):
    """Lock which way 'right' points when you look at a car's flank.

    Getting this backwards mirrors every flank render, so a number that is
    backwards on the car looks correct in the offline preview.
    """

    def test_plate_anchor_agrees_with_code(self) -> None:
        checked = 0
        for car in VConventionTests.PLATE_CARS + ("ks_mazda_miata",):
            if not (CONTENT / "cars" / car).is_dir():
                continue
            model = kn5.read_kn5(skin_livery.find_car_kn5(CONTENT, car))
            handedness, confidence = skin_uv.detect_handedness(model)
            if confidence < skin_livery.HAND_ANCHOR_MIN_CONFIDENCE:
                continue
            checked += 1
            self.assertEqual(handedness, skin_uv.HANDEDNESS, f"{car} disagrees")
        if not checked:
            self.skipTest("no car with a usable plate anchor installed")

    def test_screen_right_is_tail_on_positive_flank(self) -> None:
        np.testing.assert_allclose(skin_uv.screen_right(1.0), [0.0, 0.0, -1.0])
        np.testing.assert_allclose(skin_uv.screen_right(-1.0), [0.0, 0.0, 1.0])


class OrientationTests(unittest.TestCase):
    def test_reads_upright_catches_a_flipped_badge(self) -> None:
        badge = skin_livery.render_number_badge(220, "24")
        canvas = Image.new("RGB", (300, 300), (200, 180, 40))
        canvas.paste(badge.convert("RGB"), (40, 40), badge.getchannel("A"))
        box = (40, 40, 40 + badge.width, 40 + badge.height)

        ok, detail = skin_livery.reads_upright(canvas, box, "24")
        self.assertTrue(ok, detail)

        flipped = canvas.transpose(Image.FLIP_LEFT_RIGHT)
        mirrored_box = (canvas.width - box[2], box[1], canvas.width - box[0], box[3])
        ok, detail = skin_livery.reads_upright(flipped, mirrored_box, "24")
        self.assertFalse(ok, detail)
        self.assertIn("mirrored", detail)

    def test_orient_badge_is_identity_for_an_upright_island(self) -> None:
        badge = skin_livery.render_number_badge(120, "5")
        axes = skin_uv.IslandAxes(right=(1.0, 0.0), up=(0.0, -1.0), quality=1.0)
        same = skin_livery.orient_badge(badge, axes)
        diff = np.abs(
            np.asarray(same.convert("L"), dtype=np.int16)
            - np.asarray(badge.convert("L"), dtype=np.int16)
        )
        self.assertLess(int(diff.max()), 8)


class PlacementTests(unittest.TestCase):
    def test_matches_recorded_reference(self) -> None:
        target = miata_or_skip(self)
        placements, _ = skin_livery.plan_placements(target)
        reference = skin_livery.load_reference(CATALOG, MIATA)
        recorded = {p["side"]: tuple(p["center"]) for p in reference["placements"]}
        for placement in placements:
            self.assertEqual(placement.center, recorded[placement.side])

    def test_badge_lands_on_a_door_panel(self) -> None:
        target = miata_or_skip(self)
        placements, _ = skin_livery.plan_placements(target)
        for placement in placements:
            name, ok, detail = skin_livery._door_geometry_check(target, placement)
            self.assertTrue(ok, f"{name}: {detail}")
            self.assertIn("door", detail)

    def test_known_bad_placements_are_rejected(self) -> None:
        """The coordinates that shipped numbers onto the hood and rear bumper."""
        target = miata_or_skip(self)
        bad = skin_livery.load_json(CATALOG / "race_numbers" / f"{MIATA}.json")["known_bad"]
        for entry in bad["placements"]:
            placement = skin_livery.Placement(
                side=entry["side"], center=tuple(entry["center"]), diameter=224, inside_ratio=1.0
            )
            name, ok, detail = skin_livery._door_geometry_check(target, placement)
            self.assertFalse(ok, f"{name} should reject {entry['center']}: {detail}")
            self.assertIn(entry["panel"], detail)


    def test_badges_land_inside_door_uv_island(self) -> None:
        target = miata_or_skip(self)
        placements, masks = skin_livery.plan_placements(target)
        self.assertEqual({p.side for p in placements}, {"left", "right"})
        for placement in placements:
            self.assertAlmostEqual(placement.inside_ratio, 1.0, places=3)
            self.assertGreater(placement.diameter, 32)
            mask = masks[placement.side]
            ys, xs = skin_uv.circle_pixels(placement.center, placement.diameter, mask.shape)
            self.assertTrue(mask[ys, xs].all())

    def test_left_and_right_are_distinct_islands(self) -> None:
        target = miata_or_skip(self)
        placements, _ = skin_livery.plan_placements(target)
        centres = {p.side: p.center for p in placements}
        self.assertNotEqual(centres["left"], centres["right"])


class CompositeTests(unittest.TestCase):
    def test_badge_paints_without_destroying_the_texture(self) -> None:
        """Body diffuse ships alpha 0; alpha_composite would zero all its RGB."""
        base = Image.new("RGBA", (256, 256), (200, 40, 40, 0))
        placements = [skin_livery.Placement(side="left", center=(128, 128), diameter=64, inside_ratio=1.0)]
        out = skin_livery.apply_numbers(base, placements, 7)

        self.assertEqual(out.getpixel((5, 5))[:3], (200, 40, 40))
        centre = out.getpixel((128, 118))
        self.assertGreater(min(centre[:3]), 120)
        self.assertEqual(out.getchannel("A").getextrema(), (0, 0))

    def test_number_digits_are_dark(self) -> None:
        badge = skin_livery.render_number_badge(120, "88")
        arr = np.asarray(badge.convert("RGB")).astype(np.float32)
        lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        self.assertGreater((lum <= 90).mean(), 0.05)
        self.assertGreater((lum >= 200).mean(), 0.2)

    def test_long_numbers_still_fit_the_disc(self) -> None:
        badge = skin_livery.render_number_badge(80, "888")
        arr = np.asarray(badge.convert("RGBA"))
        edge = arr[:, :4, 3]
        self.assertEqual(int(edge.max()), 0)


class PaintTests(unittest.TestCase):
    def test_bake_tint_multiplies(self) -> None:
        base = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
        baked = skin_livery.bake_tint(base, (232, 202, 10))
        self.assertEqual(baked.getpixel((0, 0))[:3], (232, 202, 10))

    def test_neutral_detail_keeps_alpha(self) -> None:
        detail = Image.new("RGBA", (8, 8), (232, 202, 10, 77))
        neutral = skin_livery.neutral_detail(detail)
        self.assertEqual(neutral.getpixel((0, 0)), (255, 255, 255, 77))
        self.assertTrue(skin_livery.is_neutral_tint(skin_livery.texture_tint(neutral)))

    def test_cm_colour_parsing(self) -> None:
        self.assertEqual(skin_livery.parse_cm_colour("#FF01154C"), (1, 21, 76))
        self.assertEqual(skin_livery.parse_cm_colour("#01154C"), (1, 21, 76))
        self.assertIsNone(skin_livery.parse_cm_colour("nope"))
        self.assertIsNone(skin_livery.parse_cm_colour(None))

    def test_tint_match_ignores_brightness_but_not_hue(self) -> None:
        hue_error, brightness = skin_livery._tint_match((1, 21, 76), (0, 9, 33))
        self.assertLess(hue_error, 5)
        self.assertLess(brightness, 1.0)
        hue_error, _ = skin_livery._tint_match((232, 202, 10), (10, 202, 232))
        self.assertGreater(hue_error, 100)


class RenderProofTests(unittest.TestCase):
    def test_probe_footprint_locates_badge_on_render(self) -> None:
        target = miata_or_skip(self)
        placements, _ = skin_livery.plan_placements(target)
        left = [p for p in placements if p.side == "left"]
        base = skin_livery.load_base_texture(CONTENT, MIATA, MIATA_SKIN, target)
        probe = skin_livery.badge_probe_texture(base, left)
        render = skin_livery.render_proof(target, probe, side="left", width=480)
        footprint = skin_livery.badge_footprint(render)
        self.assertGreater(int(footprint.sum()), 100)
        stats = skin_livery.footprint_stats(render, footprint)
        self.assertGreater(stats["aspect"], 0.4)
        self.assertLess(stats["aspect"], 2.6)

    def test_render_of_unbadged_texture_has_no_footprint(self) -> None:
        target = miata_or_skip(self)
        base = skin_livery.load_base_texture(CONTENT, MIATA, MIATA_SKIN, target)
        render = skin_livery.render_proof(target, base, side="left", width=320)
        self.assertLess(int(skin_livery.badge_footprint(render).sum()), 20)


class ValidationTests(unittest.TestCase):
    def test_livery_png_only_skin_is_rejected(self) -> None:
        """The exact failure that shipped twice: painting the CM icon only."""
        target = miata_or_skip(self)
        report = skin_livery.validate_numbered_skin(
            content=CONTENT,
            catalog=CATALOG,
            car=MIATA,
            skin=MIATA_SKIN,  # a stock skin ships no Skin_00.dds
            number="787",
            write_report=False,
        )
        self.assertFalse(report.ok)
        names = [c.name for c in report.failures()]
        self.assertIn("texture_override_name", names)
        del target

    def test_missing_badge_is_rejected(self) -> None:
        target = miata_or_skip(self)
        placements, _ = skin_livery.plan_placements(target)
        base = skin_livery.load_base_texture(CONTENT, MIATA, MIATA_SKIN, target)
        report = skin_livery.validate_numbered_texture(
            target=target,
            base=base,
            numbered=base,  # nothing painted
            placements=[p for p in placements if p.side == "left"],
            number="787",
            skin="unpainted",
            render_width=320,
        )
        self.assertFalse(report.ok)
        names = [c.name for c in report.failures()]
        self.assertIn("badge_pixels[left]", names)
        self.assertIn("badge_changed_the_car[left]", names)

    def test_badge_outside_door_is_rejected(self) -> None:
        target = miata_or_skip(self)
        base = skin_livery.load_base_texture(CONTENT, MIATA, MIATA_SKIN, target)
        bogus = skin_livery.Placement(side="left", center=(10, 10), diameter=64, inside_ratio=0.0)
        numbered = base.convert("RGB").copy()
        ImageDraw.Draw(numbered).ellipse((0, 0, 42, 42), fill=(255, 255, 255))
        report = skin_livery.validate_numbered_texture(
            target=target,
            base=base,
            numbered=numbered.convert("RGBA"),
            placements=[bogus],
            number="787",
            skin="offdoor",
            render_width=320,
        )
        self.assertFalse(report.ok)
        self.assertIn("badge_inside_door_uv[left]", [c.name for c in report.failures()])


class EndToEndTests(unittest.TestCase):
    @unittest.skipUnless(SLOW, "pass --slow to build a real skin")
    def test_generate_and_validate_miata(self) -> None:
        target = miata_or_skip(self)
        del target
        name = "test_zz999"
        dst, report = skin_livery.generate_numbered_skin(
            content=CONTENT,
            catalog=CATALOG,
            car=MIATA,
            base_skin=MIATA_SKIN,
            number=999,
            output_skin=name,
            render_width=480,
        )
        try:
            self.assertTrue(report.ok, report.text())
            self.assertTrue((dst / "Skin_00.dds").is_file())
            again = skin_livery.validate_numbered_skin(
                content=CONTENT,
                catalog=CATALOG,
                car=MIATA,
                skin=name,
                number=999,
                base_skin=MIATA_SKIN,
                render_width=480,
                write_report=False,
            )
            self.assertTrue(again.ok, again.text())
        finally:
            import shutil

            shutil.rmtree(dst, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--slow"])
