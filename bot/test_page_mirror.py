import unittest

import page_mirror


STATICS = [
    {"id": "blackhawk", "track": "blackhawk", "name": "Practice — Blackhawk Farms", "slot": 0},
    {"id": "road-america", "track": "road-america", "name": "Practice — Road America", "slot": 1},
    {"id": "gingerman", "track": "gingerman", "name": "Practice — Gingerman Raceway", "slot": 2},
    {"id": "race-ignore", "name": "Race", "slot": 5},
]


class PageMirrorTests(unittest.TestCase):
    def test_join_urls_match_site_ports(self) -> None:
        rows = page_mirror.lobby_rows(STATICS, {"lobbies": {}}, "167.237.13.200")
        self.assertEqual([row["label"] for row in rows], ["Blackhawk", "Road America", "Gingerman"])
        self.assertEqual(
            [row["join"] for row in rows],
            [
                "https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8081",
                "https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8082",
                "https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8083",
            ],
        )

    def test_online_label_matches_web(self) -> None:
        self.assertEqual(page_mirror.online_label([]), "empty")
        self.assertEqual(page_mirror.online_label([{"name": "Isaac"}]), "Isaac")
        self.assertEqual(
            page_mirror.online_label([{"name": "Isaac"}, {"name": "Sam"}]),
            "2 online",
        )

    def test_snapshot_leads_with_join_buttons(self) -> None:
        board = {
            "updated": "2026-09-04T01:00:00+00:00",
            "lobbies": {
                "blackhawk": {"online": [{"name": "Isaac"}]},
                "road-america": {"online": []},
            },
        }
        snap = page_mirror.snapshot(
            statics=STATICS,
            board=board,
            public_ip="1.2.3.4",
            pages_url="https://simracing.fugazy.dev",
            cars=["Abarth 124 Spider", "Toyota GR86"],
        )
        self.assertEqual(snap["buttons"][0]["label"], "Blackhawk")
        self.assertIn("httpPort=8081", snap["buttons"][0]["url"])
        self.assertEqual(snap["buttons"][-1], {"label": "Player page", "url": "https://simracing.fugazy.dev/"})
        self.assertEqual(snap["fields"][0]["value"], "Isaac")
        self.assertEqual(snap["fields"][1]["value"], "empty")
        names = [field["name"] for field in snap["fields"]]
        self.assertIn("Tracks", names)
        tracks = next(field for field in snap["fields"] if field["name"] == "Tracks")
        self.assertIn("slipangle_ggt.zip", tracks["value"])
        self.assertIn("lilski_road_america.zip", tracks["value"])
        self.assertIn("gingerman_raceway.zip", tracks["value"])
        garage = next(field for field in snap["fields"] if field["name"] == "Garage")
        self.assertIn("Abarth 124 Spider", garage["value"])
        self.assertTrue(snap["footer"].startswith(page_mirror.MARKER))


if __name__ == "__main__":
    unittest.main()
